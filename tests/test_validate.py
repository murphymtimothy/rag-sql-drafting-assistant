"""Tests for the deterministic, fully-offline T-SQL validator (assistant/validate.py).

These are the end-to-end tests for Unit 1. They run with no Ollama, no DB, no network:
the validator only ever touches sqlglot and the on-disk schema_docs. The five core
cases mandated by the unit spec are grouped under TestTriggerQueryCases; the rest cover
the catalog builder and the validator's tiering (warn vs. hard-fail, cross-entity enums).

Each assertion uses a focused minimal query — the real trigger query short-circuits on
the first column-binding error, so validating the whole blob at once would only ever
surface one of its problems.
"""

import pytest

from assistant.validate import build_catalog, validate_sql

CLEAN_SQL = (
    "SELECT member_id, first_name FROM members "
    "WHERE member_since_date >= DATEADD(YEAR, -1, GETDATE())"
)


# --------------------------------------------------------------------------- #
# Schema-catalog builder
# --------------------------------------------------------------------------- #
class TestBuildCatalog:
    def test_builds_all_twenty_tables(self):
        catalog = build_catalog()
        # The repo ships exactly 20 schema docs (excluding .gitkeep).
        assert len(catalog) == 20

    def test_table_name_is_filename_stem(self):
        catalog = build_catalog()
        assert "members" in catalog
        assert "loan_status_history" in catalog

    def test_reference_docs_parsed_as_tables(self):
        # ref_status_codes / ref_channel_codes are lookup docs but still real tables.
        catalog = build_catalog()
        assert "ref_status_codes" in catalog
        assert "ref_channel_codes" in catalog
        assert "status_cd" in catalog["ref_status_codes"]
        assert "entity_type" in catalog["ref_status_codes"]

    def test_columns_and_types_extracted(self):
        catalog = build_catalog()
        members = catalog["members"]
        assert members["member_id"] == "INT"
        assert members["first_name"] == "VARCHAR(100)"
        assert members["member_since_date"] == "DATE"

    def test_header_and_separator_rows_skipped(self):
        # "column"/"type"/"---" must never leak in as column names.
        catalog = build_catalog()
        for cols in catalog.values():
            assert "column" not in cols
            assert "type" not in cols
            assert "---" not in cols
            assert "" not in cols

    def test_loan_status_history_has_no_member_id(self):
        # The crux of trigger case (a): lsh has loan_id, not member_id.
        catalog = build_catalog()
        lsh = catalog["loan_status_history"]
        assert "member_id" not in lsh
        assert "loan_id" in lsh
        assert "status_cd" in lsh

    def test_loans_and_members_have_member_id(self):
        catalog = build_catalog()
        assert "member_id" in catalog["loans"]
        assert "member_id" in catalog["members"]

    def test_only_column_section_rows_parsed(self):
        # ref_channel_codes has a "## Sample rows" line with pipes ("BRANCH = ...");
        # nothing from outside "## Columns" should appear as a column.
        catalog = build_catalog()
        channel = catalog["ref_channel_codes"]
        assert set(channel) == {
            "channel_cd",
            "channel_name",
            "is_digital",
            "description",
        }


# --------------------------------------------------------------------------- #
# The five mandated trigger-query cases
# --------------------------------------------------------------------------- #
class TestTriggerQueryCases:
    def test_a_unknown_column_on_loan_status_history(self):
        # loan_status_history has no member_id; the join predicate references it.
        sql = (
            "SELECT lsh.status_id "
            "FROM loan_status_history lsh "
            "JOIN members m ON lsh.member_id = m.member_id"
        )
        result = validate_sql(sql)
        assert result["ok"] is False
        assert any("member_id" in e for e in result["errors"])

    def test_b_undefined_lost_members_column(self):
        # 'lost_members' is never produced by the CTE, so it cannot be resolved
        # in the outer query — the undefined-column case from the trigger blob.
        sql = (
            "WITH yearly_membership_changes AS ("
            "  SELECT YEAR(member_since_date) AS membership_year, COUNT(*) AS new_members"
            "  FROM members GROUP BY YEAR(member_since_date)"
            ") "
            "SELECT membership_year, SUM(lost_members) AS lost_members "
            "FROM yearly_membership_changes GROUP BY membership_year"
        )
        result = validate_sql(sql)
        assert result["ok"] is False
        assert any("lost_members" in e for e in result["errors"])

    def test_c_postgres_limit_flagged_as_dialect(self):
        sql = "SELECT member_id FROM members LIMIT 10"
        result = validate_sql(sql)
        assert result["ok"] is False
        # Reported as a dialect/parse problem, not swallowed by column binding.
        assert any("LIMIT" in e for e in result["errors"])
        # And it must NOT have been misreported as a column-binding failure.
        assert not any("binding" in e.lower() for e in result["errors"])

    def test_d_invalid_status_enum_on_loan_query(self):
        sql = "SELECT loan_id FROM loans WHERE status_cd = 'INACTIVE'"
        result = validate_sql(sql)
        assert result["ok"] is False
        assert any("status_cd" in e and "INACTIVE" in e for e in result["errors"])

    def test_clean_tsql_query_passes(self):
        result = validate_sql(CLEAN_SQL)
        assert result["ok"] is True
        assert result["errors"] == []


# --------------------------------------------------------------------------- #
# Dialect / parse tier
# --------------------------------------------------------------------------- #
class TestDialectAndParse:
    def test_double_colon_cast_flagged(self):
        result = validate_sql("SELECT member_id::VARCHAR FROM members")
        assert result["ok"] is False
        assert any("::" in e for e in result["errors"])

    def test_backtick_identifier_flagged(self):
        result = validate_sql("SELECT `member_id` FROM members")
        assert result["ok"] is False
        assert result["errors"]  # tokenize/parse failure reported

    def test_garbage_sql_flagged_as_parse_error(self):
        result = validate_sql("SELECT FROM WHERE GROUP")
        assert result["ok"] is False
        assert result["errors"]

    def test_empty_sql_is_not_ok(self):
        assert validate_sql("")["ok"] is False
        assert validate_sql("   ")["ok"] is False

    def test_tsql_top_is_not_flagged_as_limit(self):
        # TOP is valid T-SQL and normalizes to the same Limit node as LIMIT, so the
        # check must distinguish them at the token level — TOP must pass clean.
        result = validate_sql("SELECT TOP 10 member_id FROM members")
        assert result["ok"] is True, result["errors"]

    def test_tsql_offset_fetch_is_not_flagged(self):
        sql = (
            "SELECT member_id FROM members ORDER BY member_id "
            "OFFSET 0 ROWS FETCH NEXT 10 ROWS ONLY"
        )
        result = validate_sql(sql)
        assert result["ok"] is True, result["errors"]

    def test_limit_inside_string_literal_is_not_flagged(self):
        # 'LIMIT' appearing inside a string must not trip the token scan.
        result = validate_sql("SELECT member_id FROM members WHERE first_name = 'LIMIT'")
        assert result["ok"] is True, result["errors"]


# --------------------------------------------------------------------------- #
# Enum / status-code domain tier
# --------------------------------------------------------------------------- #
class TestEnumDomain:
    def test_terminated_invalid_in_all_domains(self):
        result = validate_sql("SELECT loan_id FROM loans WHERE status_cd = 'TERMINATED'")
        assert result["ok"] is False
        assert any("TERMINATED" in e for e in result["errors"])

    def test_inactive_in_list_predicate_flagged(self):
        result = validate_sql(
            "SELECT loan_id FROM loans WHERE status_cd IN ('CURRENT', 'INACTIVE')"
        )
        assert result["ok"] is False
        assert any("INACTIVE" in e for e in result["errors"])

    def test_active_against_loan_only_query_flagged_cross_entity(self):
        # 'ACTIVE' is a valid MEMBER/ACCOUNT/CARD status but NOT a loan status, and
        # this query touches only loans — so the entity is unambiguous and it's wrong.
        result = validate_sql("SELECT loan_id FROM loans WHERE status_cd = 'ACTIVE'")
        assert result["ok"] is False
        assert any("ACTIVE" in e and "loan" in e.lower() for e in result["errors"])

    def test_valid_loan_status_passes(self):
        result = validate_sql("SELECT loan_id FROM loans WHERE status_cd = 'CURRENT'")
        assert result["ok"] is True, result["errors"]

    def test_valid_member_status_passes(self):
        result = validate_sql("SELECT member_id FROM members WHERE status_cd = 'ACTIVE'")
        assert result["ok"] is True, result["errors"]

    def test_cross_entity_not_enforced_when_ambiguous(self):
        # Two status-bearing tables (members + loans) → entity is ambiguous, so the
        # cross-entity rule is intentionally NOT enforced (documented residual gap).
        # 'ACTIVE' is valid in SOME domain, so it must not hard-fail here.
        sql = (
            "SELECT m.member_id FROM members m "
            "JOIN loans l ON m.member_id = l.member_id "
            "WHERE m.status_cd = 'ACTIVE'"
        )
        result = validate_sql(sql)
        assert result["ok"] is True, result["errors"]

    def test_status_value_invalid_everywhere_caught_even_when_ambiguous(self):
        # But a value valid in NO domain is still caught regardless of ambiguity.
        sql = (
            "SELECT m.member_id FROM members m "
            "JOIN loans l ON m.member_id = l.member_id "
            "WHERE l.status_cd = 'NONSENSE'"
        )
        result = validate_sql(sql)
        assert result["ok"] is False
        assert any("NONSENSE" in e for e in result["errors"])


# --------------------------------------------------------------------------- #
# Warn-don't-hard-fail tier and result shape
# --------------------------------------------------------------------------- #
class TestResultContract:
    def test_result_shape(self):
        result = validate_sql(CLEAN_SQL)
        assert set(result) == {"ok", "errors", "warnings"}
        assert isinstance(result["ok"], bool)
        assert isinstance(result["errors"], list)
        assert isinstance(result["warnings"], list)

    def test_select_star_does_not_hard_fail(self):
        # qualify legitimately handles SELECT * against a known table; it must not
        # become a hard error.
        result = validate_sql("SELECT * FROM members")
        assert result["ok"] is True, result["errors"]

    def test_custom_catalog_is_respected(self):
        # Passing an explicit catalog avoids reading schema_docs and lets a column
        # that is unknown there bind cleanly here.
        catalog = {"widgets": {"widget_id": "INT", "label": "VARCHAR(50)"}}
        result = validate_sql("SELECT widget_id, label FROM widgets", catalog=catalog)
        assert result["ok"] is True, result["errors"]

    def test_unknown_column_against_custom_catalog_fails(self):
        catalog = {"widgets": {"widget_id": "INT"}}
        result = validate_sql("SELECT widget_id, nonexistent FROM widgets", catalog=catalog)
        assert result["ok"] is False
        assert any("nonexistent" in e for e in result["errors"])


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
