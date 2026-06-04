"""Log every Claude API call with cost, latency and token counts.

Persists to logs/llm_calls.db (SQLite, gitignored). Designed to be called
from sql_generator.py via log_call(); the rest of the app stays unaware.

Why this matters: tracking cost and latency per call is what separates a
demo from production-grade LLM engineering. Without it there is no answer
to "how much does one query cost?" or "which question triggers retries?".
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from src.seed import PROJECT_ROOT

LOGS_DIR = PROJECT_ROOT / "logs"
DB_PATH = LOGS_DIR / "llm_calls.db"
PROJECT_NAME = "db-query-agent"

# Pricing per token in USD — Anthropic list prices as of 2025-05.
# Keys are model IDs; values have "input" and "output" cost per token.
# Add new model entries here when switching models.
_PRICING: dict[str, dict[str, float]] = {
    "claude-sonnet-4-6": {"input": 3.0 / 1_000_000, "output": 15.0 / 1_000_000},
    "claude-haiku-4-5": {"input": 0.80 / 1_000_000, "output": 4.0 / 1_000_000},
    "claude-opus-4-7": {"input": 15.0 / 1_000_000, "output": 75.0 / 1_000_000},
    # Voyage embeddings are billed per input token; output_tokens stays 0
    # in the log so the cost formula still works.
    "voyage-3-lite": {"input": 0.02 / 1_000_000, "output": 0.0},
}

_DB_INITIALIZED = False

_DDL = """
CREATE TABLE IF NOT EXISTS llm_calls (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp     TEXT    NOT NULL DEFAULT (datetime('now')),
    project       TEXT    NOT NULL,
    model         TEXT    NOT NULL,
    input_tokens  INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    latency_ms    INTEGER NOT NULL,
    cost_usd      REAL    NOT NULL,
    success       INTEGER NOT NULL,
    error_msg     TEXT
);
"""


def _init_db(db_path: Path = DB_PATH) -> None:
    global _DB_INITIALIZED
    if _DB_INITIALIZED:
        return
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(_DDL)
        conn.commit()
    finally:
        conn.close()
    _DB_INITIALIZED = True


def _compute_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Return the estimated USD cost for one API call.

    Args:
        model: Model ID string (e.g. "claude-sonnet-4-6").
        input_tokens: Tokens consumed from the prompt.
        output_tokens: Tokens in the model's response.

    Returns:
        Cost in USD, or 0.0 if the model is not in the pricing table.
        Returning 0.0 for unknown models keeps the log flowing without
        crashing — a missing price is a data gap, not a fatal error.
    """
    pricing = _PRICING.get(model)
    if pricing is None:
        return 0.0
    return input_tokens * pricing["input"] + output_tokens * pricing["output"]


def log_call(
    model: str,
    input_tokens: int,
    output_tokens: int,
    latency_ms: int,
    success: bool,
    error_msg: str | None = None,
    db_path: Path = DB_PATH,
) -> None:
    """Persist one API call record to the observability DB.

    Args:
        model: Model ID used for the call.
        input_tokens: Prompt token count from response.usage.
        output_tokens: Completion token count from response.usage.
        latency_ms: Wall-clock duration of the API call in milliseconds.
        success: True if the call returned a usable QueryPlan.
        error_msg: Error string if success is False, else None.
        db_path: Override the DB path (useful in tests).

    This function must never raise: it is called from a ``finally`` block,
    so any exception here would mask the real error from the API call.
    Failures are logged to stderr and swallowed.
    """
    try:
        cost = _compute_cost(model, input_tokens, output_tokens)

        if os.environ.get("K_SERVICE"):
            # Cloud Run: emit JSON to stdout for Cloud Logging.
            json.dump(
                {
                    "event": "llm_call",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "project": PROJECT_NAME,
                    "model": model,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "latency_ms": latency_ms,
                    "cost_usd": cost,
                    "success": success,
                    "error_msg": error_msg,
                },
                sys.stdout,
            )
            sys.stdout.write("\n")
            sys.stdout.flush()
            return

        _init_db(db_path)
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                """
                INSERT INTO llm_calls
                    (project, model, input_tokens, output_tokens,
                     latency_ms, cost_usd, success, error_msg)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    PROJECT_NAME,
                    model,
                    input_tokens,
                    output_tokens,
                    latency_ms,
                    cost,
                    int(success),
                    error_msg,
                ),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:
        print(f"[observability] log_call failed: {exc}", file=sys.stderr)
