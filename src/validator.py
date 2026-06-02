"""SQL validation and sanitization with sqlglot.

Three guarantees enforced here, in order:

1. The statement is exactly one SELECT (no DDL, DML, ATTACH, PRAGMA, ...).
2. Every referenced table is in the allow-list (the demo schema).
3. The top-level query is capped at LIMIT 100: if it has no LIMIT we inject
   one, and if it declares a larger LIMIT we lower it. Subquery and CTE
   limits are left untouched — only the root query controls how many rows
   reach the user, and capping nested ones would silently truncate
   intermediate results and corrupt the answer.

This is the *first* layer of read-only enforcement. The second layer is
the SQLite connection opened with mode=ro in src/database.py. Defense in
depth: even if a check here had a bug, the driver would still refuse a
write.
"""

from __future__ import annotations

from dataclasses import dataclass

import sqlglot
from sqlglot import expressions as exp

DEFAULT_LIMIT = 100
DIALECT = "sqlite"


class ValidationError(Exception):
    """Raised when the SQL violates one of the safety rules."""


@dataclass
class ValidationReport:
    sql: str  # the (possibly LIMIT-adjusted) SQL safe to execute
    tables_used: list[str]
    limit_injected: bool  # True if the query had no LIMIT and we added one
    limit_capped: bool  # True if an existing LIMIT exceeded the cap and was lowered


def validate(sql: str, allowed_tables: set[str]) -> ValidationReport:
    """Parse and check a SQL string. Returns a sanitized version.

    Args:
        sql: Raw SQL produced by the LLM.
        allowed_tables: Whitelist of table names that may appear.

    Returns:
        ValidationReport with the (possibly modified) SQL and metadata.

    Raises:
        ValidationError: if the SQL fails any of the three checks.
    """
    sql = sql.strip().rstrip(";").strip()
    if not sql:
        raise ValidationError("Empty SQL.")

    try:
        statements = sqlglot.parse(sql, dialect=DIALECT)
    except sqlglot.errors.ParseError as e:
        raise ValidationError(f"SQL could not be parsed: {e}") from e

    statements = [s for s in statements if s is not None]
    if len(statements) != 1:
        raise ValidationError(f"Expected exactly one statement, got {len(statements)}.")

    tree = statements[0]

    _assert_select_only(tree)
    tables_used = _collect_tables(tree)
    _assert_tables_allowed(tables_used, allowed_tables)

    final_tree, limit_injected, limit_capped = _ensure_limit(tree)
    final_sql = final_tree.sql(dialect=DIALECT)

    return ValidationReport(
        sql=final_sql,
        tables_used=sorted(tables_used),
        limit_injected=limit_injected,
        limit_capped=limit_capped,
    )


def _assert_select_only(tree: exp.Expression) -> None:
    """Reject anything other than a SELECT (or a CTE/UNION wrapping a SELECT)."""
    root = tree
    if not isinstance(root, (exp.Select, exp.Union, exp.With)):
        raise ValidationError(
            f"Only SELECT statements are allowed (got {type(root).__name__})."
        )

    # Walk the AST and reject any forbidden node type anywhere inside.
    # The root-type check above already blocks a top-level ATTACH/PRAGMA
    # (they parse to exp.Attach / exp.Pragma, not exp.Select), but we also
    # list them here so a nested occurrence is rejected explicitly instead
    # of relying on the root check. exp.Command catches VACUUM, EXPLAIN, etc.
    forbidden = (
        exp.Insert,
        exp.Update,
        exp.Delete,
        exp.Drop,
        exp.Create,
        exp.Alter,
        exp.Attach,
        exp.Detach,
        exp.Pragma,
        exp.Command,
    )
    for node in tree.walk():
        if isinstance(node, forbidden):
            raise ValidationError(f"Forbidden statement type: {type(node).__name__}.")


def _collect_tables(tree: exp.Expression) -> list[str]:
    """Return the set of base-table names referenced anywhere in the tree."""
    names: set[str] = set()
    cte_aliases: set[str] = {cte.alias_or_name for cte in tree.find_all(exp.CTE)}
    for table in tree.find_all(exp.Table):
        name = table.name
        if name and name not in cte_aliases:
            names.add(name)
    return sorted(names)


def _assert_tables_allowed(used: list[str], allowed: set[str]) -> None:
    forbidden = [t for t in used if t not in allowed]
    if forbidden:
        raise ValidationError(
            f"Query references tables outside the allow-list: {forbidden}."
        )


def _ensure_limit(tree: exp.Expression) -> tuple[exp.Expression, bool, bool]:
    """Cap the row count of the top-level query at DEFAULT_LIMIT.

    Only the root query bounds the rows returned to the user, so the cap is
    applied there and nowhere else. Subquery and CTE limits are left
    untouched: capping them could silently truncate an intermediate result
    set and produce a wrong answer with no error.

    The parsed statement is itself the root query (its ``parent`` is None),
    so we read and rewrite its LIMIT directly — ``.limit()`` returns a new
    node, replacing any existing clause.

    Args:
        tree: The parsed, already-validated top-level statement.

    Returns:
        A tuple of (possibly rewritten tree, limit_injected, limit_capped):
        ``limit_injected`` is True when no LIMIT existed and one was added;
        ``limit_capped`` is True when an existing LIMIT exceeded the cap and
        was lowered.
    """
    limit = tree.args.get("limit")
    if limit is None:
        return tree.limit(DEFAULT_LIMIT), True, False

    value = _limit_value(limit)
    if value is not None and value > DEFAULT_LIMIT:
        return tree.limit(DEFAULT_LIMIT), False, True
    return tree, False, False


def _limit_value(limit: exp.Expression) -> int | None:
    """Return the integer in a LIMIT clause, or None if it is not an integer literal.

    A non-literal LIMIT (e.g. a bound parameter or expression) can't be
    compared against the cap, so we report None and leave it untouched.
    """
    expr = limit.expression
    if isinstance(expr, exp.Literal) and expr.is_int:
        return int(expr.this)
    return None
