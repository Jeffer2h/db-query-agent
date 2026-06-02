"""Build the SQLite demo database from data/seed.sql.

Idempotent: deletes the existing .db file (if any) and rebuilds it from
the SQL script. Safe to call on every app start when the DB is missing.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "ecommerce.db"
SEED_SQL_PATH = PROJECT_ROOT / "data" / "seed.sql"


def build_database(db_path: Path = DB_PATH, seed_sql: Path = SEED_SQL_PATH) -> Path:
    """Create the demo SQLite DB by executing seed.sql.

    Args:
        db_path: Where to write the SQLite file.
        seed_sql: Path to the seed script.

    Returns:
        The absolute path of the created database.
    """
    if not seed_sql.exists():
        raise FileNotFoundError(f"Seed script not found: {seed_sql}")

    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    sql = seed_sql.read_text(encoding="utf-8")
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(sql)
        conn.commit()
    finally:
        conn.close()

    return db_path


def ensure_database(db_path: Path = DB_PATH) -> Path:
    """Build the DB only if the file does not exist yet."""
    if not db_path.exists():
        build_database(db_path)
    return db_path


if __name__ == "__main__":
    path = build_database()
    print(f"Database built at: {path}")
