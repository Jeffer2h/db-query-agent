# DB Query Agent

A text-to-SQL agent that turns natural-language questions into safe, validated
SELECT queries against an e-commerce SQLite database.

The project is a hands-on portfolio piece demonstrating three patterns that
matter when an LLM is allowed to touch a real datastore:

1. **Tool use with risk.** The agent generates and executes SQL. A malformed
   or malicious query could corrupt or leak data — so the design starts from
   the security boundary, not the other way around.
2. **RAG over the schema.** Real databases have hundreds of tables; only the
   relevant ones can fit into a prompt. The agent embeds table descriptions
   and retrieves the top-k for each question.
3. **Structured output + a self-correcting loop.** The model is forced to
   answer through a typed Pydantic schema. On validation or execution errors,
   the failure is fed back and the agent retries up to twice.

---

## What the demo does

The user asks a question in English, like:

> "Which 3 customers paid the most in 2025 via completed payments?"

The agent:

1. Embeds the question and retrieves the 5 most relevant tables.
2. Calls Claude with a forced tool-use schema, returning a `QueryPlan`
   `(sql, reasoning, tables_used)`.
3. Parses the SQL into an AST and enforces three rules: SELECT-only,
   tables in the allow-list, `LIMIT 100` injected if absent.
4. Executes against a read-only SQLite connection with a 5-second timeout.
5. If anything fails, re-prompts Claude with the previous SQL and the
   exact error message — up to 3 attempts total.
6. Renders the result table plus the SQL, the reasoning, the tables
   retrieved by RAG, and the retry history.

The UI is intentionally transparent: a recruiter should see *what* the agent
decided, not just its final answer.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  user question                                                    │
└──────────────────────────┬────────────────────────────────────────┘
                           │
                           ▼
         ┌──────────────────────────────────┐
         │  Schema retriever                │  Voyage voyage-3-lite
         │  embed(question) → top-k tables  │  + ChromaDB
         └──────────────────┬───────────────┘
                            │ (formatted schema block)
                            ▼
         ┌──────────────────────────────────┐
         │  SQL generator                   │  Claude Sonnet 4.6
         │  tool_choice: submit_query_plan  │  via Anthropic SDK
         │  → QueryPlan(sql, reasoning, ..) │
         └──────────────────┬───────────────┘
                            │
                            ▼
         ┌──────────────────────────────────┐         on error
         │  Validator (sqlglot AST)         │ ────────────────┐
         │  - SELECT only                   │                 │
         │  - tables in allow-list          │                 │
         │  - inject LIMIT 100 if missing   │                 │
         └──────────────────┬───────────────┘                 │
                            │                                 │
                            ▼                                 │
         ┌──────────────────────────────────┐  retry loop     │
         │  Executor (SQLite, mode=ro,      │  with previous  │
         │  5s timeout)                     │  error fed back │
         └──────────────────┬───────────────┘ ────────────────┘
                            │
                            ▼
                       result table
                       + reasoning
                       + SQL generated
                       + tables retrieved
                       + retry history
```

---

## Stack

| Layer | Choice | Why |
|---|---|---|
| LLM | Claude Sonnet 4.6 via Anthropic SDK | Strong tool-use + structured-output support |
| Structured output | Anthropic tool use with `tool_choice` | Anthropic's canonical pattern for typed JSON output |
| SQL parser / validator | `sqlglot` | Python-pure AST parser, multi-dialect, industry standard for text-to-SQL safety |
| Vector store | ChromaDB (persistent, local) | Free, embedded, no external service |
| Embeddings | Voyage `voyage-3-lite` via API | Keeps the Docker image small enough to deploy on free tiers; per-query cost is negligible (~$0.00002) |
| Database | SQLite with `mode=ro` URI | Reproducible demo, driver-level write protection |
| UI | Streamlit | Fast to build, sufficient for a demo |
| Observability | SQLite (`logs/llm_calls.db`) | Token counts, latency and cost logged on every Claude call |
| Tests | `pytest` | 35 tests cover validator, DB layer and observability |
| Container | Docker + docker-compose | Single `docker compose up` to run anywhere |

---

## Eval results

A 15-question eval set lives in [`data/eval_questions.json`](data/eval_questions.json).
For each question, the agent's SQL is executed and its result set is compared
against a hand-written reference query (order-insensitive, floats rounded).

| Iteration | Score | Notes |
|---|---|---|
| Baseline prompt | **11/15 (73%)** | Two related failures (Q06, Q13): the prompt rule *"prefer `payments.amount` for revenue"* over-counted when joining with item-level filters |
| After prompt refinement | **13/15 (87%)** | Rule rewritten to distinguish aggregate revenue (`payments.amount`) from per-attribute revenue (`order_items.quantity * unit_price`) |
| After eval question cleanup | **15/15 (100%)** | Two questions reworded to remove genuine ambiguity (column selection and tie-breaking not specified in originals) |

Run it yourself:

```bash
docker compose run --rm app uv run python -m src.eval
```

The retry loop did not fire in any run — all answers came on the first
attempt (1.00 avg). The loop is exercised manually in development but,
with this schema and these questions, Sonnet 4.6 produces valid SQL on
the first try.

---

## Key technical decisions

### Defense in depth for read-only enforcement

Two independent layers refuse writes:

1. **Validator (sqlglot AST).** Rejects any node type that isn't a SELECT
   (Insert, Update, Delete, Drop, Alter, Attach, Pragma, ...). Walks the
   *entire* tree, so a subquery cannot smuggle in a DML statement.
2. **SQLite driver.** The connection is opened with the URI
   `file:ecommerce.db?mode=ro`. Even if a bug in the validator let a write
   through, the driver would refuse it.

The tests include the deliberately tricky case `SELECT name FROM customers
WHERE name = 'DROP'` — a regex-based check would falsely block this; the
AST-based validator correctly accepts it because the literal string is not
a node.

### Structured output via forced tool use

Anthropic does not expose `response_format=json_schema` like OpenAI. The
canonical pattern is to define a tool whose `input_schema` mirrors the
desired output, then set `tool_choice={"type": "tool", "name": ...}` to
force the model to answer through that tool. The result is JSON validated
against the schema, then parsed into a Pydantic `QueryPlan`.

### Voyage embeddings instead of a local sentence-transformers model

An earlier version of this project embedded the schema with a local
`sentence-transformers/all-MiniLM-L6-v2` model. That works, but it drags
PyTorch into the image (~2 GB) and adds 10–30 seconds of cold-start time
on free deployment platforms. Since this project only embeds six short
table descriptions plus one query per question, paying for ~50 tokens of
Voyage `voyage-3-lite` per query (about $0.000001) is the right trade-off.
The image is now ~400 MB and the embedder uses Voyage's `input_type`
distinction (`document` at index time, `query` at retrieval time) for a
small but free retrieval quality bump. Project 01 keeps the hybrid
local/API setup because embeddings *are* the concept being demonstrated
there; here, they are infrastructure.

### Why schema retrieval matters at six tables

This demo only has six tables, so technically all of them would fit in
the prompt. The retrieval is included anyway because:

- The pattern is what scales (50, 200, 1000 tables).
- The descriptions are *natural language*, not raw column lists. Embedding
  `"orders: id, customer_id, order_date"` makes poor matches with user
  questions like *"how much did we sell?"* — embedding `"Customer orders.
  Each order has a date and a status..."` makes good matches. The quality
  of the retrieval depends almost entirely on these descriptions.

### LIMIT injection instead of LIMIT rejection

If the model omits `LIMIT`, the validator silently injects `LIMIT 100`.
The alternative — rejecting the query and asking the model to retry — would
double API cost on a benign mistake. Injection is also a useful production
pattern: it caps blast radius from a runaway query that returns millions
of rows.

### Query timeout via SQLite's progress handler

SQLite has no native query timeout. The standard workaround is
`conn.set_progress_handler(callback, n_ops)`: SQLite calls the callback
every *n_ops* virtual-machine instructions; returning truthy aborts the
query. More reliable than threads or signals, and the reaction time is
sub-millisecond.

### `unit_price` is stored on `order_items` on purpose

`order_items.unit_price` snapshots the price paid for an item at the time
of purchase. This is redundant with `products.price`, but it is a real
e-commerce invariant: prices change over time, and a historical order must
reflect the price the customer actually paid. The system prompt instructs
the agent to use `unit_price` for revenue, never `products.price`.

---

## Guardrails summary

| Layer | What it enforces |
|---|---|
| Structured output | The model returns JSON, not free text |
| AST validation | SELECT-only; tables in allow-list; no ATTACH / PRAGMA |
| LIMIT injection | Caps result at 100 rows when the query has no `LIMIT` |
| Read-only connection | SQLite opened with `?mode=ro` |
| Query timeout | 5 seconds via progress handler |
| Retry budget | Max 3 attempts; error from each failure fed back to the model |

---

## Observability

Every Claude API call **and** every Voyage embedding call is logged to
`logs/llm_calls.db` (SQLite, gitignored).

| Metric | Typical value |
|---|---|
| Input tokens per query | ~1 700 |
| Output tokens per query | ~195 |
| Cost per query | ~$0.008 |
| Latency per query | ~4.1 s |
| Success rate (eval, 30 calls) | 100% |

Costs are estimated using Anthropic list pricing; the per-token rates live in
`_PRICING` in `src/observability.py`, which is the source of truth — update both
that table and the figures above when switching models. The log schema is
`(id, timestamp, project, model, input_tokens, output_tokens, latency_ms, cost_usd, success, error_msg)`.
The logger is designed to be non-fatal: a filesystem error (disk full,
permission denied) prints to stderr and returns without raising, so it
can never replace the real exception when used inside a `finally` block.

---

## Lessons learned

- **The system prompt is where domain knowledge lives.** The single biggest
  jump in eval score came from a four-line rewrite of one rule about how
  to compute revenue. Code changes didn't move the needle; the prompt did.
- **A naive rule beats nothing, but a careful rule beats a naive one.**
  The first version of the revenue rule (*"prefer `payments.amount`"*) was
  almost right and quietly wrong in two specific cases. Eval surfaced both.
- **An eval set is itself a piece of software** that needs design and
  iteration. Two of my fifteen original questions had ambiguous intent;
  cleaning them up was as important as improving the agent.
- **Schema descriptions, not table names, are what RAG matches against.**
  This is obvious in retrospect but easy to under-invest in.

---

## Next iterations (out of scope for v1)

- **Multi-DB support.** Hard-coded to the e-commerce schema. A
  meaningful next step is letting the user point at any SQLite file and
  having the retriever index it.
- **Larger eval set + per-category breakdown.** 15 questions is too few
  to be statistically meaningful. A 100-question set, tagged by question
  type, would give a much sharper picture of where the agent fails.
- **Conversation memory.** Follow-up questions like *"break that down by month"* need a chat buffer; currently every question is independent.

---

## How to run

You need a Claude API key and a Voyage AI API key (free tier is enough
for this demo).

```bash
cp .env.example .env          # paste your ANTHROPIC_API_KEY and VOYAGE_API_KEY
docker compose up --build
```

Open http://localhost:8502 in your browser.

The first run builds the SQLite DB from `data/seed.sql` and indexes the
schema in ChromaDB. Subsequent runs reuse both.

### Run the tests

```bash
docker compose run --rm app uv run pytest -v
```

### Run the eval

```bash
docker compose run --rm app uv run python -m src.eval
```

---

## Project structure

```
db-query-agent/
├── README.md
├── CLAUDE.md               internal context for the AI assistant
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
├── .env.example
├── app.py                  Streamlit UI
├── src/
│   ├── seed.py             builds ecommerce.db from seed.sql
│   ├── database.py         read-only connection, query execution, timeout
│   ├── schema_retriever.py ChromaDB + Voyage embeddings indexing
│   ├── sql_generator.py    Claude tool-use call, returns QueryPlan
│   ├── validator.py        sqlglot AST checks + LIMIT injection
│   ├── agent.py            orchestrator with retry loop
│   ├── observability.py    logs every Claude call to logs/llm_calls.db
│   └── eval.py             runs the eval suite and reports a score
├── data/
│   ├── seed.sql            DDL + INSERTs for the demo e-commerce DB
│   ├── eval_questions.json 15 questions with reference SQL
│   ├── ecommerce.db        (gitignored, generated)
│   └── chroma/             (gitignored, generated)
└── tests/
    ├── test_validator.py   20 cases covering all guardrails
    ├── test_database.py    smoke + read-only enforcement
    └── test_observability.py  11 cases: cost calc, DB writes, resilience
```
