import re
from pathlib import Path

SCHEMA_DOCS = Path(__file__).parent.parent / "schema_docs"

_SQL_NOISE = {
    "select", "from", "where", "join", "inner", "left", "right", "outer",
    "on", "and", "or", "not", "null", "is", "as", "by", "order", "group",
    "having", "limit", "top", "distinct", "with", "case", "when", "then",
    "else", "end", "in", "between", "like", "exists", "all", "any",
    "sum", "count", "avg", "min", "max", "coalesce", "isnull", "getdate",
}
_DECLINE_PHRASES = [
    "cannot", "can't", "not in the schema", "don't have", "no table",
    "unable to find", "not found in", "does not exist", "no information",
    "not available in", "outside the scope",
    # broader model-generated decline patterns
    "none of the tables", "not contain", "no columns", "not included",
    "not part of", "not present in", "schema does not", "schema context does not",
    "no such table", "not covered", "not supported by", "beyond the scope",
    "unfortunately", "not provided in", "not reflected in",
    "don't see", "do not see", "i don't see", "i do not see",
]


def _load_schema_names(schema_docs: Path = SCHEMA_DOCS) -> tuple[set[str], set[str]]:
    """Parse all schema doc filenames and column tables to get valid table/column names."""
    tables: set[str] = set()
    columns: set[str] = set()
    header_words = {"column", "type", "nullable", "description", "example", "---"}

    for doc in schema_docs.glob("*.md"):
        tables.add(doc.stem.lower())
        content = doc.read_text(encoding="utf-8")
        for match in re.finditer(r"^\|\s*(\w+)\s*\|", content, re.MULTILINE):
            word = match.group(1).lower()
            if word not in header_words:
                columns.add(word)

    return tables, columns


def _extract_sql_identifiers(sql: str) -> tuple[set[str], set[str]]:
    """Lightweight extraction of table and column identifiers from a SQL string."""
    if not sql or not sql.strip():
        return set(), set()

    sql_lower = sql.lower()
    sql_clean = re.sub(r"'[^']*'", " ", sql_lower)

    tables: set[str] = set()
    columns: set[str] = set()
    aliases: set[str] = set()

    # FROM/JOIN <table> [AS] [alias] — capture both the table and any alias so the
    # dotted-reference pass below can tell real tables apart from table aliases.
    for match in re.finditer(
        r"(?:from|join)\s+(\w+)(?:\s+(?:as\s+)?(\w+))?", sql_clean
    ):
        name, alias = match.group(1), match.group(2)
        if name not in _SQL_NOISE and len(name) > 2:
            tables.add(name)
        if alias and alias not in _SQL_NOISE:
            aliases.add(alias)

    # <ident>.<column> — the left side may be a table or a declared alias. Only
    # treat it as a table when it is not a known alias; otherwise a multi-char
    # alias (e.g. "lsh") would be mis-scored as a hallucinated table name.
    for match in re.finditer(r"(\w+)\.(\w+)", sql_clean):
        left, right = match.group(1), match.group(2)
        if left not in _SQL_NOISE and left not in aliases and len(left) > 1:
            tables.add(left)
        if right not in _SQL_NOISE and len(right) > 2:
            columns.add(right)

    return tables, columns


def check_answer(
    result: dict,
    expected_tables: list[str],
    expected_columns: list[str],
    schema_docs: Path = SCHEMA_DOCS,
) -> dict:
    """
    Score a result dict from answer_question() against expected tables/columns.

    Trick questions have expected_tables=[] — scored on whether the model
    correctly declined to generate SQL rather than hallucinating.

    Returns {"score": float, "reason": str}.
    Score: 1.0 = fully correct, 0.5 = partial match, 0.0 = failure.
    """
    schema_tables, schema_columns = _load_schema_names(schema_docs)
    sql = (result.get("sql") or "").strip()
    # Normalize typographic apostrophes/quotes so phrase matching works regardless
    # of whether the model used smart quotes or ASCII.
    explanation = (result.get("explanation") or "").lower()
    explanation = explanation.replace("’", "'").replace("‘", "'")

    if not expected_tables:
        if sql:
            return {
                "score": 0.0,
                "reason": "Generated SQL despite no valid schema match — should have declined",
            }
        if any(phrase in explanation for phrase in _DECLINE_PHRASES):
            return {
                "score": 1.0,
                "reason": "Correctly declined to answer: schema gap acknowledged",
            }
        return {
            "score": 0.0,
            "reason": "No SQL but no explicit acknowledgment of schema gap",
        }

    if not sql:
        return {"score": 0.0, "reason": "No SQL generated"}

    ref_tables, ref_columns = _extract_sql_identifiers(sql)

    hallucinated = {
        t for t in ref_tables
        if t not in schema_tables and len(t) > 2
    }
    if hallucinated:
        return {
            "score": 0.0,
            "reason": f"Hallucinated table names: {', '.join(sorted(hallucinated))}",
        }

    expected_set = {t.lower() for t in expected_tables}
    matched = expected_set & ref_tables

    if matched == expected_set:
        return {
            "score": 1.0,
            "reason": f"All expected tables present: {', '.join(sorted(matched))}",
        }
    if matched:
        missing = expected_set - matched
        return {
            "score": 0.5,
            "reason": f"Partial match — found {sorted(matched)}, missing {sorted(missing)}",
        }
    return {
        "score": 0.0,
        "reason": f"Expected tables not referenced: {', '.join(sorted(expected_set))}",
    }
