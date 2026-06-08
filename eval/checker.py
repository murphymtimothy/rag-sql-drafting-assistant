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
    # additional observed model decline phrasings
    "does not include", "does not contain", "no mention", "there is no",
    "i apologize", "not include any", "no such", "isn't a table", "is not a table",
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
    # Drop T-SQL bracket quoting so [dbo].[members] reads like dbo.members (remove the
    # brackets without inserting whitespace, which would break the schema.table dot).
    sql_clean = sql_clean.replace("[", "").replace("]", "")

    tables: set[str] = set()
    columns: set[str] = set()
    aliases: set[str] = set()

    # Query-local names that are NOT schema tables but can appear on the left of a
    # dotted reference: CTE names from WITH ... AS (...) and derived-table aliases
    # written as ") alias". Collect them so they aren't mistaken for real tables.
    aliases |= set(re.findall(r"(?:with|,)\s+(\w+)\s+as\s*\(", sql_clean))
    for match in re.finditer(r"\)\s+(?:as\s+)?(\w+)", sql_clean):
        if match.group(1) not in _SQL_NOISE:
            aliases.add(match.group(1))

    # Object-name schema qualifiers (e.g. dbo.members) — the qualifier is not a table.
    schema_qualifiers = {"dbo", "sys", "information_schema", "guest"}

    # FROM/JOIN [schema.]<table> [AS] [alias]. The optional "\w+\." swallows a schema
    # qualifier; derived tables (FROM/JOIN "(") simply don't match and are skipped.
    for match in re.finditer(
        r"(?:from|join)\s+(?:\w+\.)?(\w+)(?:\s+(?:as\s+)?(\w+))?", sql_clean
    ):
        name, alias = match.group(1), match.group(2)
        # `name not in aliases` skips CTE names used as a table (e.g. JOIN <cte>),
        # since CTE names were collected into `aliases` before this pass.
        if (
            name not in _SQL_NOISE
            and name not in schema_qualifiers
            and name not in aliases
            and len(name) > 2
        ):
            tables.add(name)
        if alias and alias not in _SQL_NOISE:
            aliases.add(alias)

    # <ident>.<column> — the left side may be a table, a declared alias, a CTE name,
    # or a schema qualifier. Only treat it as a table when it is none of those;
    # otherwise an alias (e.g. "lsh") or CTE name would be mis-scored as a table.
    for match in re.finditer(r"(\w+)\.(\w+)", sql_clean):
        left, right = match.group(1), match.group(2)
        if (
            left not in _SQL_NOISE
            and left not in aliases
            and left not in schema_qualifiers
            and len(left) > 1
        ):
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

    expected_set = {t.lower() for t in expected_tables}

    if not sql:
        # No SQL — accept a prose answer that explicitly names the expected table(s).
        # "Which table tracks X?" and "What columns does Y have?" are naturally
        # answered in prose, so credit expected table names that appear as whole words.
        named = {
            t for t in expected_set
            if re.search(rf"\b{re.escape(t)}\b", explanation)
        }
        if named == expected_set:
            return {
                "score": 1.0,
                "reason": f"Prose answer names all expected tables: {', '.join(sorted(named))}",
            }
        if named:
            return {
                "score": 0.5,
                "reason": f"Prose answer — found {sorted(named)}, missing {sorted(expected_set - named)}",
            }
        return {"score": 0.0, "reason": "No SQL generated and no expected table named in prose"}

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
