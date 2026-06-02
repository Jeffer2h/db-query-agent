"""Read-only access layer to the demo SQLite database.

Two responsibilities:
- Open the DB in read-only mode (defense-in-depth: even if a non-SELECT
  slipped past the validator, the driver would refuse it).
- Execute queries with a wall-clock timeout, so a runaway query cannot
  block the UI.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

from src.seed import DB_PATH


class ColumnInfo(TypedDict):
    """A single column's metadata, as read from PRAGMA table_info."""

    name: str
    type: str
    not_null: bool


class TableInfo(TypedDict):
    """A table and its columns, the unit the schema retriever indexes."""

    name: str
    columns: list[ColumnInfo]


class QueryTimeoutError(Exception):
    """Raised when a query exceeds the configured timeout."""


class QueryExecutionError(Exception):
    """Raised when SQLite rejects the query (syntax, missing table, etc)."""


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[tuple[object, ...]]

    @property
    def row_count(self) -> int:
        return len(self.rows)


def _connect_readonly(db_path: Path) -> sqlite3.Connection:
    """Open the DB through a URI so we can force mode=ro."""
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}. Run src.seed first.")
    uri = f"file:{db_path}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def _install_timeout(conn: sqlite3.Connection, timeout_s: float) -> None:
    """Abort the current query if wall-clock time exceeds timeout_s.

    SQLite calls the progress handler every N virtual-machine ops; we
    return a non-zero value to signal interruption.
    """
    deadline = time.monotonic() + timeout_s

    def _handler() -> int:
        return 1 if time.monotonic() > deadline else 0

    # 1000 VM ops between checks: low overhead, sub-ms reaction time.
    conn.set_progress_handler(_handler, 1000)


def execute(sql: str, timeout_s: float = 5.0, db_path: Path = DB_PATH) -> QueryResult:
    """Run a SELECT query against the demo DB.

    Args:
        sql: Already-validated SELECT statement.
        timeout_s: Wall-clock limit before aborting.
        db_path: Path to the SQLite file.

    Returns:
        QueryResult with column names and rows.

    Raises:
        QueryTimeoutError: if the query exceeds timeout_s.
        QueryExecutionError: for SQLite errors (syntax, unknown table, ...).
    """
    conn = _connect_readonly(db_path)
    try:
        _install_timeout(conn, timeout_s)
        cursor = conn.cursor()
        try:
            cursor.execute(sql)
        except sqlite3.OperationalError as e:
            if "interrupted" in str(e).lower():
                raise QueryTimeoutError(
                    f"Query exceeded timeout of {timeout_s}s"
                ) from e
            raise QueryExecutionError(str(e)) from e
        except sqlite3.DatabaseError as e:
            raise QueryExecutionError(str(e)) from e

        columns = [d[0] for d in cursor.description] if cursor.description else []
        rows = cursor.fetchall()
        return QueryResult(columns=columns, rows=rows)
    finally:
        conn.close()


def list_tables_metadata(db_path: Path = DB_PATH) -> list[TableInfo]:
    """Inspect the schema for the retriever to index.

    Returns one entry per user table with its name and column list.
    """
    conn = _connect_readonly(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name"
        )
        table_names = [row[0] for row in cursor.fetchall()]

        tables: list[TableInfo] = []
        for name in table_names:
            cursor.execute(f"PRAGMA table_info({name})")
            columns: list[ColumnInfo] = [
                {"name": col[1], "type": col[2], "not_null": bool(col[3])}
                for col in cursor.fetchall()
            ]
            tables.append({"name": name, "columns": columns})
        return tables
    finally:
        conn.close()
