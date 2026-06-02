"""Tests for the orchestrator's retry loop.

The headline behavior of the agent is "self-correction": when a generated
SQL fails (either validation or execution), the error is fed back to the
generator on the next attempt, and the loop terminates after MAX_ATTEMPTS.

These tests pin that behavior with fake collaborators so we never hit the
real Claude or Voyage APIs.
"""

from __future__ import annotations

from src.agent import Agent, MAX_ATTEMPTS
from src.schema_retriever import RetrievedTable
from src.sql_generator import FailedAttempt, QueryPlan


class FakeGenerator:
    """SqlGenerator stand-in that returns pre-programmed QueryPlans.

    Records each call so tests can assert that the retry loop forwarded
    previous failures to the next attempt.
    """

    def __init__(self, responses: list[QueryPlan]) -> None:
        self._responses = list(responses)
        self.calls: list[list[FailedAttempt]] = []

    def generate(
        self,
        question: str,
        schema_block: str,
        failures: list[FailedAttempt],
    ) -> QueryPlan:
        self.calls.append(list(failures))
        return self._responses.pop(0)


class FakeRetriever:
    """SchemaRetriever stand-in that returns a fixed set of tables."""

    def __init__(self, tables: list[RetrievedTable]) -> None:
        self._tables = tables

    def retrieve(self, question: str, k: int = 5) -> list[RetrievedTable]:
        return self._tables


FAKE_TABLES = [
    RetrievedTable(
        name="customers",
        columns=[
            {"name": "id", "type": "INTEGER", "not_null": True},
            {"name": "name", "type": "TEXT", "not_null": False},
        ],
        description="customers table",
    ),
]


def _plan(sql: str, tables: list[str]) -> QueryPlan:
    return QueryPlan(sql=sql, reasoning="test", tables_used=tables)


def test_succeeds_on_first_try_without_retries():
    gen = FakeGenerator([_plan("SELECT name FROM customers LIMIT 5", ["customers"])])
    agent = Agent(retriever=FakeRetriever(FAKE_TABLES), generator=gen)

    result = agent.answer("list customers")

    assert result.succeeded
    assert len(result.attempts) == 1
    # The first call must receive an empty failure list.
    assert gen.calls == [[]]


def test_retry_loop_recovers_after_invalid_sql():
    """Bad SQL → error fed back → next attempt succeeds."""
    gen = FakeGenerator(
        [
            _plan("SELECT * FROM nonexistent_table", ["nonexistent_table"]),
            _plan("SELECT name FROM customers LIMIT 5", ["customers"]),
        ]
    )
    agent = Agent(retriever=FakeRetriever(FAKE_TABLES), generator=gen)

    result = agent.answer("list customers")

    assert result.succeeded
    assert len(result.attempts) == 2
    # First call: no prior failures. Second call: exactly one prior failure
    # (the rejected table), proving the loop forwards error context.
    assert gen.calls[0] == []
    assert len(gen.calls[1]) == 1
    assert "nonexistent_table" in gen.calls[1][0].error


def test_retry_loop_gives_up_after_max_attempts():
    """All attempts fail → loop terminates with final_error set."""
    gen = FakeGenerator(
        [_plan("SELECT * FROM nonexistent_table", ["nonexistent_table"])]
        * MAX_ATTEMPTS
    )
    agent = Agent(retriever=FakeRetriever(FAKE_TABLES), generator=gen)

    result = agent.answer("anything")

    assert not result.succeeded
    assert len(result.attempts) == MAX_ATTEMPTS
    assert result.final_error is not None
    assert "Gave up" in result.final_error


def test_needs_clarification_short_circuits_loop():
    """If the model asks for clarification, the agent stops immediately."""
    gen = FakeGenerator(
        [
            QueryPlan(
                sql="",
                reasoning="ambiguous question",
                tables_used=[],
                needs_clarification=True,
                clarification_question="Which time period?",
            )
        ]
    )
    agent = Agent(retriever=FakeRetriever(FAKE_TABLES), generator=gen)

    result = agent.answer("how are sales?")

    assert not result.succeeded
    assert result.needs_clarification
    assert result.clarification_question == "Which time period?"
    assert len(result.attempts) == 1
