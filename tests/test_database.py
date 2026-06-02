"""Smoke tests for the database layer and seed script."""

from __future__ import annotations

import pytest

from src.database import (
    QueryExecutionError,
    execute,
    list_tables_metadata,
)
from src.seed import build_database

EXPECTED_TABLES = {
    "customers",
    "categories",
    "products",
    "orders",
    "order_items",
    "payments",
}


@pytest.fixture(scope="module", autouse=True)
def _build_db():
    build_database()


def test_all_tables_created():
    names = {t["name"] for t in list_tables_metadata()}
    assert names == EXPECTED_TABLES


def test_seed_populates_expected_row_counts():
    counts = {
        t["name"]: execute(f"SELECT COUNT(*) FROM {t['name']}").rows[0][0]
        for t in list_tables_metadata()
    }
    assert counts["categories"] == 6
    assert counts["products"] == 30
    assert counts["customers"] == 12
    assert counts["orders"] == 60
    assert counts["order_items"] > 0
    assert counts["payments"] > 0


def test_readonly_connection_rejects_writes():
    """Even if the validator missed it, the driver must refuse a write."""
    with pytest.raises(QueryExecutionError):
        execute(
            "INSERT INTO customers (id, name, email, country, created_at) "
            "VALUES (999, 'x', 'x@x', 'X', '2025-01-01')"
        )


def test_bad_sql_raises_typed_error():
    with pytest.raises(QueryExecutionError):
        execute("SELECT * FROM table_that_does_not_exist")
