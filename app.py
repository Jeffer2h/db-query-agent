"""Streamlit UI for the db-query-agent.

The user types a natural-language question; the agent generates SQL,
validates it, runs it against the demo SQLite DB, and the UI renders the
result alongside the agent's reasoning, the generated SQL, and the
schema tables retrieved by RAG. Transparency is a feature: a recruiter
should see what the agent decided, not just its final answer.
"""

from __future__ import annotations

import os

import pandas as pd
import streamlit as st

from src.agent import Agent, AgentResult
from src.database import execute, list_tables_metadata
from src.schema_retriever import TABLE_DESCRIPTIONS
from src.seed import DB_PATH, ensure_database

EXAMPLE_QUESTIONS = [
    "What are the top 5 best-selling products by units sold?",
    "How much revenue did we collect in electronics?",
    "Which 3 customers spent the most money in 2025?",
    "Which country has the most customers?",
    "What payment methods are most popular?",
    "How many orders were cancelled in 2025?",
]


@st.cache_data(show_spinner=False)
def get_table_counts() -> dict[str, int]:
    """Return row count per table. Cached so it runs once per session.

    Must be called after ensure_database() has run (i.e. after get_agent()).
    """
    if not DB_PATH.exists():
        return {}
    tables = list_tables_metadata()
    return {
        t["name"]: execute(f"SELECT COUNT(*) FROM {t['name']}").rows[0][0]
        for t in tables
    }


@st.cache_data(show_spinner=False)
def get_table_sample(
    table_name: str, limit: int = 5
) -> tuple[list[str], list[tuple[object, ...]]]:
    """Return a small sample of rows from a table.

    Must be called after ensure_database() has run (i.e. after get_agent()).
    """
    if not DB_PATH.exists():
        return [], []
    result = execute(f"SELECT * FROM {table_name} LIMIT {limit}")
    return result.columns, result.rows


def render_schema_sidebar() -> None:
    """Render an explorable schema panel in the sidebar."""
    with st.sidebar:
        st.header("Database Schema")
        st.caption(
            "Demo e-commerce database. Expand any table to see its "
            "columns and sample rows before asking a question."
        )
        st.divider()

        tables = list_tables_metadata()
        counts = get_table_counts()

        for table in tables:
            name = table["name"]
            count = counts.get(name, 0)
            with st.expander(f"**{name}** — {count:,} rows"):
                description = TABLE_DESCRIPTIONS.get(name, "")
                if description:
                    st.caption(description)

                schema_rows = [
                    (c["name"], c["type"], "✓" if c["not_null"] else "")
                    for c in table["columns"]
                ]
                st.dataframe(
                    pd.DataFrame(schema_rows, columns=["Column", "Type", "NOT NULL"]),
                    hide_index=True,
                    use_container_width=True,
                )

                cols, rows = get_table_sample(name)
                if rows:
                    st.caption("Sample rows:")
                    st.dataframe(
                        pd.DataFrame(rows, columns=cols),
                        hide_index=True,
                        use_container_width=True,
                    )


@st.cache_resource(show_spinner="Building database and schema index...")
def get_agent() -> Agent:
    """Instantiate the agent once per session.

    Loads the embedding model, builds the Chroma index if needed and
    seeds the SQLite DB on first run. Subsequent calls return the cached
    instance.
    """
    ensure_database()
    return Agent()


def render_result_table(columns: list[str], rows: list[tuple[object, ...]]) -> None:
    if not rows:
        st.info("Query returned no rows.")
        return
    df = pd.DataFrame(rows, columns=columns)
    st.dataframe(df, use_container_width=True, hide_index=True)


def render_run(result: AgentResult) -> None:
    if result.needs_clarification:
        st.warning("The agent needs more context to answer:")
        st.markdown(f"> {result.clarification_question}")
        return

    final = result.final_attempt
    if final is None:
        st.error(result.final_error or "No attempts were made.")
        return

    if final.succeeded and final.result is not None:
        st.success(f"Answered in {len(result.attempts)} attempt(s).")
        render_result_table(final.result.columns, final.result.rows)
    else:
        st.error(result.final_error or final.error or "Query failed.")

    with st.expander("SQL generated", expanded=False):
        sql = final.validation.sql if final.validation else final.plan.sql
        st.code(sql, language="sql")
        if final.validation and final.validation.limit_injected:
            st.caption("`LIMIT 100` was injected automatically (query had no LIMIT).")
        elif final.validation and final.validation.limit_capped:
            st.caption("The query's `LIMIT` exceeded 100 and was capped to 100.")

    with st.expander("Agent reasoning", expanded=False):
        st.markdown(final.plan.reasoning)

    with st.expander(
        f"Tables retrieved by RAG ({len(result.retrieved_tables)})",
        expanded=False,
    ):
        for t in result.retrieved_tables:
            cols = ", ".join(c["name"] for c in t.columns)
            st.markdown(f"**{t.name}** — {cols}")

    if len(result.attempts) > 1:
        with st.expander(f"Retry history ({len(result.attempts)} attempts)"):
            for i, attempt in enumerate(result.attempts, start=1):
                st.markdown(f"**Attempt {i}**")
                st.code(attempt.plan.sql, language="sql")
                if attempt.error:
                    st.error(attempt.error)
                elif attempt.succeeded:
                    st.success("Succeeded.")


def _fill_question(question: str) -> None:
    """Copy an example question into the input box (button on_click callback)."""
    st.session_state["question"] = question


def main() -> None:
    st.set_page_config(page_title="DB Query Agent", page_icon="🗄️", layout="wide")
    st.title("DB Query Agent")
    st.caption(
        "Ask a question in natural language. The agent retrieves the "
        "relevant tables, generates a SELECT query, validates it, and "
        "runs it against a demo e-commerce database."
    )

    if not os.getenv("ANTHROPIC_API_KEY"):
        st.error("ANTHROPIC_API_KEY is not set. Edit `.env` and rebuild the container.")
        return

    agent = get_agent()
    render_schema_sidebar()

    st.markdown("**Example questions** (click to fill the input):")
    cols = st.columns(2)
    for i, q in enumerate(EXAMPLE_QUESTIONS):
        # on_click fires the callback before the text_area is instantiated on
        # the next rerun, so writing session_state["question"] here is safe.
        # Assigning to a widget key inline (after the widget exists) would
        # raise StreamlitAPIException.
        cols[i % 2].button(
            q,
            key=f"ex_{i}",
            use_container_width=True,
            on_click=_fill_question,
            args=(q,),
        )

    with st.form("ask"):
        question = st.text_area(
            "Your question",
            key="question",
            height=80,
            placeholder="e.g. How much did we sell last month?",
        )
        submitted = st.form_submit_button("Run", type="primary")

    if submitted and question.strip():
        # Top-level safety net: any unhandled failure from Claude / Voyage /
        # ChromaDB / SQLite reaches Streamlit as a friendly message instead of
        # a stacktrace. Observability already records the underlying error.
        try:
            with st.spinner("Thinking..."):
                result = agent.answer(question.strip())
        except Exception as e:  # noqa: BLE001 — last resort, surface to the user
            st.error(f"The agent failed: {type(e).__name__}: {e}")
            return
        render_run(result)


if __name__ == "__main__":
    main()
