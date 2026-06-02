"""Tests for the observability module.

Covers cost calculation, DB persistence, directory creation,
and the critical invariant that observability failures never
propagate to the caller.
"""

from __future__ import annotations

import sqlite3

import pytest

import src.observability as obs_module
from src.observability import _compute_cost, log_call


@pytest.fixture(autouse=True)
def reset_init_flag():
    """Reset the module-level _DB_INITIALIZED flag before each test.

    The flag is process-scoped. Without this reset, the first test that
    calls log_call would mark the DB as initialized, causing subsequent
    tests with different db_path values to skip _init_db entirely and
    write into whatever path was first used.
    """
    obs_module._DB_INITIALIZED = False
    yield
    obs_module._DB_INITIALIZED = False


# ── Cost calculation ──────────────────────────────────────────────────────────


class TestComputeCost:
    def test_known_model_input_price(self):
        # claude-sonnet-4-6 input: $3 per million tokens
        cost = _compute_cost("claude-sonnet-4-6", 1_000_000, 0)
        assert cost == pytest.approx(3.0)

    def test_known_model_output_price(self):
        # claude-sonnet-4-6 output: $15 per million tokens
        cost = _compute_cost("claude-sonnet-4-6", 0, 1_000_000)
        assert cost == pytest.approx(15.0)

    def test_known_model_combined(self):
        cost = _compute_cost("claude-sonnet-4-6", 1000, 200)
        expected = 1000 * 3.0 / 1_000_000 + 200 * 15.0 / 1_000_000
        assert cost == pytest.approx(expected)

    def test_unknown_model_returns_zero(self):
        assert _compute_cost("claude-does-not-exist", 1000, 200) == 0.0

    def test_zero_tokens_returns_zero(self):
        assert _compute_cost("claude-sonnet-4-6", 0, 0) == 0.0


# ── DB persistence ────────────────────────────────────────────────────────────


class TestLogCall:
    def test_success_row_written(self, tmp_path):
        db = tmp_path / "calls.db"
        log_call("claude-sonnet-4-6", 500, 100, 1200, True, db_path=db)

        row = (
            sqlite3.connect(db)
            .execute(
                "SELECT project, model, input_tokens, output_tokens, "
                "latency_ms, success, error_msg FROM llm_calls"
            )
            .fetchone()
        )

        assert row == ("db-query-agent", "claude-sonnet-4-6", 500, 100, 1200, 1, None)

    def test_failure_row_written(self, tmp_path):
        db = tmp_path / "calls.db"
        log_call(
            "claude-sonnet-4-6",
            400,
            0,
            800,
            False,
            error_msg="Model returned no tool_use block",
            db_path=db,
        )

        row = (
            sqlite3.connect(db)
            .execute("SELECT success, error_msg FROM llm_calls")
            .fetchone()
        )

        assert row == (0, "Model returned no tool_use block")

    def test_cost_usd_persisted(self, tmp_path):
        db = tmp_path / "calls.db"
        log_call("claude-sonnet-4-6", 1000, 200, 1000, True, db_path=db)

        cost = (
            sqlite3.connect(db).execute("SELECT cost_usd FROM llm_calls").fetchone()[0]
        )

        expected = _compute_cost("claude-sonnet-4-6", 1000, 200)
        assert cost == pytest.approx(expected)

    def test_multiple_calls_accumulate(self, tmp_path):
        db = tmp_path / "calls.db"
        log_call("claude-sonnet-4-6", 100, 50, 500, True, db_path=db)
        log_call("claude-sonnet-4-6", 200, 80, 700, True, db_path=db)

        count = (
            sqlite3.connect(db).execute("SELECT COUNT(*) FROM llm_calls").fetchone()[0]
        )
        assert count == 2

    def test_creates_logs_directory(self, tmp_path):
        db = tmp_path / "nested" / "subdir" / "calls.db"
        assert not db.parent.exists()

        log_call("claude-sonnet-4-6", 100, 50, 500, True, db_path=db)

        assert db.exists()


# ── Resilience ────────────────────────────────────────────────────────────────


class TestResilience:
    def test_init_failure_does_not_propagate(self, monkeypatch, tmp_path):
        """Observability must never raise — not even if the DB cannot be created.

        The critical invariant: a disk-full or permission error in _init_db
        must not replace the caller's real exception (e.g. SqlGenerationError)
        when log_call is used inside a finally block.
        """

        def _always_fail(db_path=None):
            raise OSError("simulated disk full")

        monkeypatch.setattr(obs_module, "_init_db", _always_fail)

        # Must complete without raising
        log_call(
            "claude-sonnet-4-6",
            100,
            50,
            500,
            True,
            db_path=tmp_path / "irrelevant.db",
        )
