from pathlib import Path
import pytest
from eval.checker import check_answer, _extract_sql_identifiers, _load_schema_names


# --- _extract_sql_identifiers ---

def test_extract_identifiers_basic_select():
    sql = "SELECT m.member_id, m.first_name FROM members m"
    tables, columns = _extract_sql_identifiers(sql)
    assert "members" in tables
    assert "member_id" in columns

def test_extract_identifiers_join():
    sql = (
        "SELECT m.member_id, l.loan_id, lsh.days_past_due "
        "FROM members m "
        "JOIN loans l ON m.member_id = l.member_id "
        "JOIN loan_status_history lsh ON l.loan_id = lsh.loan_id "
        "WHERE lsh.end_date IS NULL"
    )
    tables, columns = _extract_sql_identifiers(sql)
    assert "members" in tables
    assert "loans" in tables
    assert "loan_status_history" in tables

def test_extract_identifiers_empty_sql():
    tables, columns = _extract_sql_identifiers("")
    assert tables == set()
    assert columns == set()

def test_extract_identifiers_excludes_multichar_aliases():
    # A 3-char table alias used in dotted refs must NOT be picked up as a table.
    sql = (
        "SELECT lsh.days_past_due FROM loan_status_history lsh "
        "WHERE lsh.end_date IS NULL"
    )
    tables, columns = _extract_sql_identifiers(sql)
    assert "loan_status_history" in tables
    assert "lsh" not in tables
    assert "days_past_due" in columns


# --- _load_schema_names ---

def test_load_schema_names_returns_table_from_filename(minimal_schema_docs):
    tables, columns, column_tables = _load_schema_names(minimal_schema_docs)
    assert "members" in tables
    assert "loans" in tables

def test_load_schema_names_returns_columns(minimal_schema_docs):
    tables, columns, column_tables = _load_schema_names(minimal_schema_docs)
    assert "member_id" in columns
    assert "first_name" in columns

def test_load_schema_names_maps_column_to_tables(minimal_schema_docs):
    # member_id is defined on BOTH members and loans; first_name only on members.
    _, _, column_tables = _load_schema_names(minimal_schema_docs)
    assert column_tables["member_id"] == {"members", "loans"}
    assert column_tables["first_name"] == {"members"}
    assert "credit_score" not in column_tables


# --- check_answer: standard questions ---

def test_check_answer_full_match(minimal_schema_docs):
    result = {
        "sql": "SELECT m.member_id, l.loan_id FROM members m JOIN loans l ON m.member_id = l.member_id",
        "explanation": "Joins members to loans.",
    }
    out = check_answer(result, ["members", "loans"], ["member_id", "loan_id"], minimal_schema_docs)
    assert out["score"] == 1.0
    assert "members" in out["reason"].lower() or "all" in out["reason"].lower()

def test_check_answer_partial_match(minimal_schema_docs):
    result = {
        "sql": "SELECT member_id FROM members",
        "explanation": "Only queries members.",
    }
    out = check_answer(result, ["members", "loans"], ["member_id"], minimal_schema_docs)
    assert out["score"] == 0.5

def test_check_answer_nonexistent_column_referenced_in_sql(minimal_schema_docs):
    # SQL references a column (credit_score) that exists in NO schema table.
    # The query's tables are valid, so the OLD table-only scoring returned 1.0;
    # column-aware scoring must drop it below 1.0 and name the offending column.
    result = {
        "sql": "SELECT m.member_id, m.credit_score FROM members m",
        "explanation": "Returns each member's credit score.",
    }
    out = check_answer(result, ["members"], ["member_id"], minimal_schema_docs)
    assert out["score"] < 1.0
    assert "credit_score" in out["reason"].lower()

def test_check_answer_nonexistent_expected_column(minimal_schema_docs):
    # The expected_columns list itself names a column absent from every table.
    result = {
        "sql": "SELECT m.member_id FROM members m",
        "explanation": "Returns member ids.",
    }
    out = check_answer(result, ["members"], ["member_id", "credit_score"], minimal_schema_docs)
    assert out["score"] < 1.0
    assert "credit_score" in out["reason"].lower()

def test_check_answer_all_columns_exist_scores_full(minimal_schema_docs):
    # Correct query whose referenced columns all exist AND every expected_column is
    # present in the schema — column-aware scoring must still award 1.0.
    result = {
        "sql": (
            "SELECT m.member_id, m.first_name, l.loan_id, l.days_past_due "
            "FROM members m JOIN loans l ON m.member_id = l.member_id"
        ),
        "explanation": "Joins members to loans, all real columns.",
    }
    out = check_answer(
        result,
        ["members", "loans"],
        ["member_id", "first_name", "loan_id", "days_past_due"],
        minimal_schema_docs,
    )
    assert out["score"] == 1.0
    assert "credit_score" not in out["reason"].lower()

def test_check_answer_multichar_alias_not_hallucinated(minimal_schema_docs):
    # Regression: correct query using multi-char aliases must score 1.0, not be
    # mis-flagged as hallucinating the aliases ("mem", "ln") as table names.
    result = {
        "sql": (
            "SELECT mem.member_id, ln.loan_id "
            "FROM members mem JOIN loans ln ON mem.member_id = ln.member_id"
        ),
        "explanation": "Joins members to loans using multi-character aliases.",
    }
    out = check_answer(result, ["members", "loans"], ["member_id", "loan_id"], minimal_schema_docs)
    assert out["score"] == 1.0
    assert "hallucinated" not in out["reason"].lower()

def test_check_answer_hallucinated_table(minimal_schema_docs):
    result = {
        "sql": "SELECT * FROM member_delinquency_summary",
        "explanation": "Queries a summary table.",
    }
    out = check_answer(result, ["loans"], [], minimal_schema_docs)
    assert out["score"] == 0.0
    assert "hallucinated" in out["reason"].lower()

def test_check_answer_no_sql(minimal_schema_docs):
    result = {"sql": "", "explanation": "I cannot determine the table."}
    out = check_answer(result, ["members"], [], minimal_schema_docs)
    assert out["score"] == 0.0
    assert "no sql" in out["reason"].lower()


# --- check_answer: trick questions (expected_tables=[]) ---

def test_check_answer_trick_correct_decline(minimal_schema_docs):
    result = {
        "sql": "",
        "explanation": "I cannot answer this from the provided schema context — there is no table for investment portfolios.",
    }
    out = check_answer(result, [], [], minimal_schema_docs)
    assert out["score"] == 1.0

def test_check_answer_trick_hallucinated_sql(minimal_schema_docs):
    result = {
        "sql": "SELECT * FROM investment_portfolios",
        "explanation": "Here is the query.",
    }
    out = check_answer(result, [], [], minimal_schema_docs)
    assert out["score"] == 0.0
    assert "declined" in out["reason"].lower() or "sql" in out["reason"].lower()

def test_check_answer_trick_no_acknowledgment(minimal_schema_docs):
    result = {"sql": "", "explanation": "Here is some general information about portfolios."}
    out = check_answer(result, [], [], minimal_schema_docs)
    assert out["score"] == 0.0
    assert "acknowledgment" in out["reason"].lower()


# --- hardening regressions: schema prefixes, CTE/derived aliases, prose, declines ---

def test_extract_identifiers_ignores_schema_prefix():
    # T-SQL schema qualification: dbo is a schema, not a table.
    tables, _ = _extract_sql_identifiers("SELECT m.member_id FROM dbo.members AS m")
    assert "members" in tables
    assert "dbo" not in tables

def test_extract_identifiers_ignores_bracket_quoting():
    tables, _ = _extract_sql_identifiers("SELECT * FROM [dbo].[members]")
    assert "members" in tables
    assert "dbo" not in tables

def test_extract_identifiers_ignores_cte_and_derived_alias():
    sql = (
        "WITH latest AS (SELECT card_account_id, MAX(transaction_date) d "
        "FROM card_rewards GROUP BY card_account_id) "
        "SELECT ca.card_account_id, latest.d "
        "FROM card_accounts ca "
        "JOIN (SELECT card_account_id FROM card_rewards) sub "
        "  ON ca.card_account_id = sub.card_account_id "
        "JOIN latest ON ca.card_account_id = latest.card_account_id"
    )
    tables, _ = _extract_sql_identifiers(sql)
    assert "card_accounts" in tables
    assert "card_rewards" in tables
    assert "latest" not in tables   # CTE name, not a table
    assert "sub" not in tables      # derived-table alias, not a table

def test_check_answer_dbo_prefixed_not_hallucinated(minimal_schema_docs):
    result = {"sql": "SELECT m.member_id FROM dbo.members AS m", "explanation": "x"}
    out = check_answer(result, ["members"], [], minimal_schema_docs)
    assert out["score"] == 1.0
    assert "hallucinated" not in out["reason"].lower()

def test_check_answer_prose_lookup_names_table(minimal_schema_docs):
    # "Which table tracks X?" answered in prose with no SQL — should still get credit.
    result = {"sql": "", "explanation": "You should use the members table for that."}
    out = check_answer(result, ["members"], [], minimal_schema_docs)
    assert out["score"] == 1.0

def test_check_answer_trick_decline_phrasing_variant(minimal_schema_docs):
    # Observed real decline wording that the original phrase list missed.
    result = {
        "sql": "",
        "explanation": (
            "I apologize, but the schema context provided does not include any "
            "information about credit scores. There is no mention of such a table."
        ),
    }
    out = check_answer(result, [], [], minimal_schema_docs)
    assert out["score"] == 1.0
