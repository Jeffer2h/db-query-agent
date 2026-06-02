"""Tests for the SQL validator.

The validator is the agent's first line of defense. These tests cover
the three guarantees: SELECT-only, table allow-list, and forced LIMIT.
"""

from __future__ import annotations

import pytest

from src.validator import DEFAULT_LIMIT, ValidationError, validate

ALLOWED = {"customers", "categories", "products", "orders", "order_items", "payments"}


class TestAcceptsLegitSelects:
    """Queries that should be accepted, possibly with LIMIT injected."""

    def test_plain_select(self):
        report = validate("SELECT name FROM customers", ALLOWED)
        assert report.tables_used == ["customers"]
        assert report.limit_injected is True

    def test_select_with_existing_limit(self):
        report = validate("SELECT * FROM orders LIMIT 5", ALLOWED)
        assert report.limit_injected is False

    def test_join_two_tables(self):
        sql = (
            "SELECT c.name, COUNT(*) FROM orders o "
            "JOIN customers c ON c.id = o.customer_id GROUP BY c.name"
        )
        report = validate(sql, ALLOWED)
        assert set(report.tables_used) == {"customers", "orders"}

    def test_cte_alias_is_not_treated_as_table(self):
        sql = "WITH x AS (SELECT id FROM orders) SELECT COUNT(*) FROM x"
        report = validate(sql, ALLOWED)
        assert "x" not in report.tables_used
        assert "orders" in report.tables_used

    def test_union(self):
        sql = "SELECT id FROM orders UNION SELECT id FROM customers"
        report = validate(sql, ALLOWED)
        assert set(report.tables_used) == {"customers", "orders"}

    def test_trailing_semicolon_is_stripped(self):
        validate("SELECT 1;", ALLOWED)  # no exception

    def test_limit_injection_uses_default(self):
        report = validate("SELECT * FROM products", ALLOWED)
        assert f"LIMIT {DEFAULT_LIMIT}" in report.sql.upper()


class TestLimitEnforcement:
    """The cap must bound the rows returned to the user without corrupting them."""

    def test_huge_limit_is_capped(self):
        report = validate("SELECT * FROM orders LIMIT 999999", ALLOWED)
        assert report.limit_capped is True
        assert report.limit_injected is False
        assert f"LIMIT {DEFAULT_LIMIT}" in report.sql.upper()
        assert "999999" not in report.sql

    def test_limit_at_cap_is_untouched(self):
        report = validate(f"SELECT * FROM orders LIMIT {DEFAULT_LIMIT}", ALLOWED)
        assert report.limit_capped is False
        assert report.limit_injected is False

    def test_small_limit_is_preserved(self):
        report = validate("SELECT * FROM orders LIMIT 5", ALLOWED)
        assert report.limit_capped is False
        assert report.limit_injected is False
        assert "LIMIT 5" in report.sql.upper()

    def test_subquery_limit_is_not_injected(self):
        """Only the outer query is capped; capping a subquery would truncate it."""
        sql = "SELECT * FROM orders WHERE customer_id IN (SELECT id FROM customers)"
        report = validate(sql, ALLOWED)
        # Exactly one LIMIT, on the outer query — the subquery is left alone.
        assert report.sql.upper().count("LIMIT") == 1
        assert report.limit_injected is True

    def test_union_huge_limit_is_capped(self):
        sql = "SELECT id FROM orders UNION SELECT id FROM customers LIMIT 999999"
        report = validate(sql, ALLOWED)
        assert report.limit_capped is True
        assert "999999" not in report.sql
        assert f"LIMIT {DEFAULT_LIMIT}" in report.sql.upper()

    def test_union_without_limit_gets_limit_injected(self):
        sql = "SELECT id FROM orders UNION SELECT id FROM customers"
        report = validate(sql, ALLOWED)
        assert report.limit_injected is True
        assert f"LIMIT {DEFAULT_LIMIT}" in report.sql.upper()

    def test_cte_huge_limit_is_capped(self):
        sql = "WITH x AS (SELECT id FROM orders) SELECT * FROM x LIMIT 999999"
        report = validate(sql, ALLOWED)
        assert report.limit_capped is True
        assert "999999" not in report.sql

    def test_parenthesized_subquery_as_root_is_rejected(self):
        """A bare subquery at the root is not a valid top-level statement."""
        with pytest.raises(ValidationError):
            validate("(SELECT id FROM orders LIMIT 999999)", ALLOWED)


class TestRejectsWrites:
    """Anything that mutates state must be rejected."""

    @pytest.mark.parametrize(
        "sql",
        [
            "INSERT INTO customers (name) VALUES ('x')",
            "UPDATE products SET price = 0",
            "DELETE FROM orders",
            "DROP TABLE customers",
            "ALTER TABLE products ADD COLUMN x INT",
        ],
    )
    def test_dml_and_ddl_rejected(self, sql: str):
        with pytest.raises(ValidationError):
            validate(sql, ALLOWED)


class TestRejectsDangerousCommands:
    """ATTACH and PRAGMA can leak data or alter behavior."""

    def test_attach_rejected(self):
        with pytest.raises(ValidationError):
            validate('ATTACH DATABASE "evil.db" AS evil', ALLOWED)

    def test_pragma_rejected(self):
        with pytest.raises(ValidationError):
            validate("PRAGMA table_info(customers)", ALLOWED)


class TestStructuralChecks:
    def test_multiple_statements_rejected(self):
        with pytest.raises(ValidationError):
            validate("SELECT 1; SELECT 2", ALLOWED)

    def test_empty_sql_rejected(self):
        with pytest.raises(ValidationError):
            validate("   ", ALLOWED)

    def test_unparseable_sql_rejected(self):
        with pytest.raises(ValidationError):
            validate("SELEKT * FROM customers", ALLOWED)


class TestAllowList:
    def test_table_outside_allow_list_rejected(self):
        with pytest.raises(ValidationError):
            validate("SELECT * FROM sqlite_master", ALLOWED)

    def test_misspelled_table_rejected(self):
        with pytest.raises(ValidationError):
            validate("SELECT * FROM customer", ALLOWED)  # missing 's'

    def test_string_literal_matching_forbidden_word_is_safe(self):
        """A literal containing 'DROP' must not trip the validator."""
        report = validate("SELECT name FROM customers WHERE name = 'DROP'", ALLOWED)
        assert report.tables_used == ["customers"]


class TestBypassAttempts:
    """Adversarial inputs that try to slip past the validator.

    Each test pins one specific vector. Together they document the threat
    model the guardrail defends against — a reviewer can read this class and
    see "yes, they thought about these attacks".
    """

    # --- Vector A: UNION reaching a table outside the allow-list -----------

    def test_union_with_forbidden_table_is_rejected(self):
        # The first SELECT is legitimate; the second pulls metadata out of
        # sqlite_master. A validator that only inspected the root query would
        # miss this. _collect_tables() walks the whole tree, so the allow-list
        # check fires.
        with pytest.raises(ValidationError, match="allow-list"):
            validate(
                "SELECT id FROM orders "
                "UNION ALL "
                "SELECT name FROM sqlite_master",
                ALLOWED,
            )

    # --- Vector B: DDL keyword hidden in SQL comments ----------------------

    def test_line_comment_with_ddl_keyword_is_safe(self):
        # A regex-based filter that scans for "DROP" anywhere in the string
        # would reject this. sqlglot strips comments during parsing, so the
        # statement is a plain SELECT and must validate cleanly.
        report = validate(
            "SELECT * FROM customers WHERE id = 1 -- ; DROP TABLE customers",
            ALLOWED,
        )
        assert report.tables_used == ["customers"]

    def test_block_comment_with_ddl_keyword_is_safe(self):
        report = validate(
            "/* DROP TABLE customers */ SELECT * FROM customers",
            ALLOWED,
        )
        assert report.tables_used == ["customers"]

    # --- Vector C: ATTACH appearing as data vs. as a nested command --------

    def test_string_literal_attach_is_safe(self):
        # 'ATTACH DATABASE ...' as a value cannot mutate state; the validator
        # must not confuse a literal with a command. Complements the
        # corresponding 'DROP' literal test above.
        report = validate(
            "SELECT name FROM customers WHERE name = 'ATTACH DATABASE evil'",
            ALLOWED,
        )
        assert report.tables_used == ["customers"]

    def test_nested_attach_inside_cte_is_rejected(self):
        # ATTACH cannot live inside a CTE in valid SQLite syntax, so sqlglot
        # refuses to parse the construct in the first place — which is also a
        # rejection. We accept either failure mode (ValidationError raised
        # from parse error OR from the AST walk) as evidence the bypass fails.
        with pytest.raises(ValidationError):
            validate(
                "WITH x AS (ATTACH DATABASE 'evil.db' AS evil) "
                "SELECT * FROM customers",
                ALLOWED,
            )
