"""Run the eval set and report how many questions the agent answers correctly.

For each question we:
1. Run the agent end-to-end (retrieve → generate → validate → execute).
2. Execute the reference SQL directly against the DB.
3. Compare the two result sets (order-insensitive, floats rounded).

A pass is when both produce the same multiset of rows.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from src.agent import Agent
from src.database import QueryResult, execute
from src.seed import PROJECT_ROOT, ensure_database

EVAL_PATH = PROJECT_ROOT / "data" / "eval_questions.json"
FLOAT_PRECISION = 2


@dataclass
class EvalCase:
    id: int
    question: str
    reference_sql: str


@dataclass
class EvalOutcome:
    case: EvalCase
    passed: bool
    attempts: int
    agent_sql: str | None
    agent_rows: list[tuple[object, ...]] | None
    reference_rows: list[tuple[object, ...]]
    error: str | None = None


def _normalize_rows(result: QueryResult) -> list[tuple[object, ...]]:
    """Sort rows and round floats so equivalent results compare equal."""
    normalized: list[tuple[object, ...]] = []
    for row in result.rows:
        normalized.append(
            tuple(round(v, FLOAT_PRECISION) if isinstance(v, float) else v for v in row)
        )
    return sorted(normalized, key=lambda r: tuple(str(v) for v in r))


def load_cases(path: Path = EVAL_PATH) -> list[EvalCase]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [EvalCase(**item) for item in raw]


def run_case(case: EvalCase, agent: Agent) -> EvalOutcome:
    reference = execute(case.reference_sql)
    ref_rows = _normalize_rows(reference)

    agent_result = agent.answer(case.question)
    last = agent_result.final_attempt

    if agent_result.needs_clarification:
        return EvalOutcome(
            case=case,
            passed=False,
            attempts=len(agent_result.attempts),
            agent_sql=None,
            agent_rows=None,
            reference_rows=ref_rows,
            error="Agent asked for clarification.",
        )

    if not (last and last.succeeded and last.result is not None):
        return EvalOutcome(
            case=case,
            passed=False,
            attempts=len(agent_result.attempts),
            agent_sql=last.plan.sql if last else None,
            agent_rows=None,
            reference_rows=ref_rows,
            error=agent_result.final_error or (last.error if last else "no attempts"),
        )

    agent_rows = _normalize_rows(last.result)
    sql_used = last.validation.sql if last.validation else last.plan.sql
    return EvalOutcome(
        case=case,
        passed=agent_rows == ref_rows,
        attempts=len(agent_result.attempts),
        agent_sql=sql_used,
        agent_rows=agent_rows,
        reference_rows=ref_rows,
    )


def run_all(verbose: bool = True) -> list[EvalOutcome]:
    ensure_database()
    cases = load_cases()
    agent = Agent()

    outcomes: list[EvalOutcome] = []
    for case in cases:
        start = time.monotonic()
        outcome = run_case(case, agent)
        elapsed = time.monotonic() - start
        outcomes.append(outcome)
        if verbose:
            mark = "PASS" if outcome.passed else "FAIL"
            print(
                f"[{mark}] Q{case.id:02d} ({elapsed:4.1f}s, "
                f"{outcome.attempts}x) {case.question}"
            )
            if not outcome.passed:
                if outcome.error:
                    print(f"       error: {outcome.error}")
                if outcome.agent_sql:
                    print(f"       agent: {outcome.agent_sql}")
                print(f"       agent rows : {outcome.agent_rows}")
                print(f"       expected   : {outcome.reference_rows}")
    return outcomes


def summarize(outcomes: list[EvalOutcome]) -> None:
    passed = sum(1 for o in outcomes if o.passed)
    total = len(outcomes)
    print()
    print("=" * 60)
    print(f"Score: {passed}/{total} ({100 * passed / total:.1f}%)")
    avg_attempts = sum(o.attempts for o in outcomes) / total if total else 0
    print(f"Average attempts per question: {avg_attempts:.2f}")


if __name__ == "__main__":
    summarize(run_all())
