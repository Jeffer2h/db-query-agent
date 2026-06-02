"""Orchestrator: retrieve schema → generate SQL → validate → execute, with retries.

Each attempt that fails (validation or execution) is fed back to the
generator as context for the next attempt. After MAX_ATTEMPTS the agent
gives up and returns the accumulated history so the UI can show what
happened.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.database import (
    QueryExecutionError,
    QueryResult,
    QueryTimeoutError,
    execute,
    list_tables_metadata,
)
from src.schema_retriever import RetrievedTable, SchemaRetriever
from src.sql_generator import (
    FailedAttempt,
    QueryPlan,
    SqlGenerationError,
    SqlGenerator,
)
from src.validator import ValidationError, ValidationReport, validate

MAX_ATTEMPTS = 3  # 1 initial try + up to 2 retries


@dataclass
class AgentAttempt:
    """A single try inside the loop, successful or not."""

    plan: QueryPlan
    validation: ValidationReport | None = None
    error: str | None = None
    result: QueryResult | None = None

    @property
    def succeeded(self) -> bool:
        return self.result is not None


@dataclass
class AgentResult:
    """Full record of an agent run, for the UI to render transparently."""

    question: str
    retrieved_tables: list[RetrievedTable]
    attempts: list[AgentAttempt] = field(default_factory=list)
    needs_clarification: bool = False
    clarification_question: str | None = None
    final_error: str | None = None

    @property
    def succeeded(self) -> bool:
        return bool(self.attempts) and self.attempts[-1].succeeded

    @property
    def final_attempt(self) -> AgentAttempt | None:
        return self.attempts[-1] if self.attempts else None


class Agent:
    """Glue between retriever, generator, validator and database."""

    def __init__(
        self,
        retriever: SchemaRetriever | None = None,
        generator: SqlGenerator | None = None,
    ) -> None:
        # No side effects here: the caller (app.py) is responsible for
        # ensuring the DB exists, and the retriever builds its index
        # lazily on the first retrieve() call. Keeping __init__ pure makes
        # the agent trivial to instantiate with mocks in tests.
        self._retriever = retriever or SchemaRetriever()
        self._generator = generator or SqlGenerator()
        self._allowed_tables = {t["name"] for t in list_tables_metadata()}

    def answer(self, question: str) -> AgentResult:
        tables = self._retriever.retrieve(question)
        schema_block = SchemaRetriever.format_for_prompt(tables)

        result = AgentResult(question=question, retrieved_tables=tables)
        failures: list[FailedAttempt] = []

        for _ in range(MAX_ATTEMPTS):
            try:
                plan = self._generator.generate(question, schema_block, failures)
            except SqlGenerationError as e:
                result.final_error = f"Generator error: {e}"
                return result

            attempt = AgentAttempt(plan=plan)
            result.attempts.append(attempt)

            if plan.needs_clarification:
                result.needs_clarification = True
                result.clarification_question = plan.clarification_question
                return result

            try:
                report = validate(plan.sql, self._allowed_tables)
            except ValidationError as e:
                attempt.error = f"Validation failed: {e}"
                failures.append(FailedAttempt(sql=plan.sql, error=str(e)))
                continue

            attempt.validation = report

            try:
                attempt.result = execute(report.sql)
                return result
            except (QueryExecutionError, QueryTimeoutError) as e:
                attempt.error = f"Execution failed: {e}"
                failures.append(FailedAttempt(sql=report.sql, error=str(e)))
                continue

        result.final_error = f"Gave up after {MAX_ATTEMPTS} attempts."
        return result
