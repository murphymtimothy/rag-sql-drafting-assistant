"""Deterministic, fully-offline SQL validator for the RAG text-to-SQL assistant.

The assistant drafts Microsoft SQL Server / T-SQL. LLM drafts routinely hallucinate
columns or slip in another dialect's syntax, and nothing downstream catches it before
it reaches an analyst. ``validate_sql`` is that gate: it parses and column-binds a draft
against a catalog built from ``schema_docs/*.md`` using :mod:`sqlglot`, with zero network
or database access.

Three deterministic checks, in order (sequencing matters — see ``validate_sql``):

1. **Dialect / parse.** Reject non-T-SQL syntax (a Postgres-style ``LIMIT``, ``::``
   casts, MySQL backticks) and unparseable SQL *before* any column binding, so a
   dialect slip is reported as such rather than swallowed by the binder.
2. **Column binding.** ``sqlglot.optimizer.qualify.qualify`` with
   ``validate_qualify_columns=True`` (the default) raises on unknown / unresolvable
   columns — this is what catches ``loan_status_history.member_id`` (no such column)
   and an undefined alias like ``lost_members``. Optimizer errors we cannot classify
   as a genuine binding failure are downgraded to warnings (``qualify`` legitimately
   trips on some constructs); they never turn a valid query into a hard failure.
3. **Enum / status-code domain.** Flag a ``status_cd`` literal that is valid in no
   known entity domain, and — where a table's entity is unambiguous — a literal valid
   only in a *different* entity (e.g. ``'ACTIVE'`` against a loan).

Public surface: ``validate_sql(sql) -> {"ok": bool, "errors": [str], "warnings": [str]}``
and ``build_catalog()`` (the schema-catalog builder, exposed for tests / reuse).
"""

from __future__ import annotations

import re
from pathlib import Path

import sqlglot
from sqlglot import exp
from sqlglot.errors import OptimizeError, ParseError, SqlglotError, TokenError
from sqlglot.optimizer.qualify import qualify
from sqlglot.tokens import TokenType

# Same anchor pattern the rest of the codebase uses (see eval/checker.py,
# assistant/sql_assistant.py): schema_docs sits at the repo root.
SCHEMA_DOCS = Path(__file__).parent.parent / "schema_docs"

DIALECT = "tsql"

# The uniform schema-doc column table header:
#   | Column | Type | Nullable | Description | Example |
#   |---|---|---|---|---|
# The header is identified POSITIONALLY by its first two cells (Column, Type) rather
# than by matching any single cell against {"column", "type", ...}: "Description" is
# both a header label AND a real column name in the reference docs (ref_channel_codes,
# ref_status_codes), so a value-based skip would silently drop that column.
_HEADER_CELL1, _HEADER_CELL2 = "column", "type"

# A markdown table row: leading "|", then the first two cells we care about, then "|".
_TABLE_ROW = re.compile(r"^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|")


# --------------------------------------------------------------------------- #
# 1. Schema-catalog builder
# --------------------------------------------------------------------------- #
def build_catalog(schema_docs: Path = SCHEMA_DOCS) -> dict[str, dict[str, str]]:
    """Parse every ``schema_docs/*.md`` into a sqlglot schema map.

    Returns ``{table: {column: type}}`` where ``table`` is the filename stem
    (lower-cased to match T-SQL's case-insensitive identifier resolution) and the
    column/type pairs come from the doc's uniform markdown column table::

        | Column | Type | Nullable | Description | Example |
        |---|---|---|---|---|
        | member_id | INT | NOT NULL | ... | 10042 |

    Only the first two cells of each data row (column name, SQL type) are read; the
    header row and the ``|---|`` separator are skipped. Reference/lookup docs
    (``ref_status_codes.md``, ``ref_channel_codes.md``) are parsed as ordinary tables
    too, since their columns can legitimately appear in a query.
    """
    catalog: dict[str, dict[str, str]] = {}

    for doc in sorted(schema_docs.glob("*.md")):
        table = doc.stem.lower()
        columns: dict[str, str] = {}

        in_column_section = False
        for line in doc.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()

            # Only read rows under the "## Columns" heading. Later sections
            # ("## Foreign keys", "## Sample rows") may contain pipes we must ignore.
            if stripped.startswith("## "):
                in_column_section = stripped.lower() == "## columns"
                continue
            if not in_column_section:
                continue

            match = _TABLE_ROW.match(stripped)
            if not match:
                continue

            col_name, col_type = match.group(1).strip(), match.group(2).strip()

            # Skip the header row ("| Column | Type | ..."), matched on both cells so a
            # column literally named "description" is NOT mistaken for the header.
            if col_name.lower() == _HEADER_CELL1 and col_type.lower() == _HEADER_CELL2:
                continue
            # Skip the "|---|---|" separator row (cells are all dashes/colons).
            if set(col_name) <= {"-", ":"} or not col_name:
                continue
            # A real column name is a single SQL identifier; defend against any
            # stray prose row that happens to start with a pipe.
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", col_name):
                continue

            columns[col_name.lower()] = col_type

        if columns:
            catalog[table] = columns

    return catalog


# --------------------------------------------------------------------------- #
# 2/4. Enum (status-code) domains
# --------------------------------------------------------------------------- #
# These domains are NOT enumerated in ref_status_codes.md (that doc only lists the
# entity_type values and a couple of examples). The actual code values live in prose
# in the operational docs — e.g. loan_status_history.md / loans.md spell out the loan
# codes, and members/accounts/card_accounts use 'ACTIVE'. They are hardcoded here.
_ENUM_DOMAINS: dict[str, set[str]] = {
    "LOAN": {"CURRENT", "DLQ_30", "DLQ_60", "DLQ_90", "CHARGE_OFF", "PAID_OFF"},
    # MEMBER / ACCOUNT / CARD: 'ACTIVE' is the only value the docs assert by name.
    # Kept conservative on purpose — we only ever flag a literal that is valid in NO
    # domain, or (for an unambiguous table) valid only in a *different* entity. We do
    # not flag a literal that simply isn't in this set, to avoid false positives on
    # legitimate-but-undocumented statuses.
    "MEMBER": {"ACTIVE"},
    "ACCOUNT": {"ACTIVE"},
    "CARD": {"ACTIVE"},
}

# Maps a base table name to the entity_type whose status domain governs its status_cd.
_TABLE_ENTITY: dict[str, str] = {
    "members": "MEMBER",
    "accounts": "ACCOUNT",
    "loans": "LOAN",
    "loan_status_history": "LOAN",
    "card_accounts": "CARD",
}

# Union of every status value across all entity domains: a literal outside this set
# is invalid everywhere (catches 'INACTIVE' / 'TERMINATED').
_ALL_ENUM_VALUES: set[str] = set().union(*_ENUM_DOMAINS.values())

# NOTE on residual gap (intentional, documented): for a multi-join query that touches
# several status-bearing tables, an unqualified or cross-entity status_cd literal can
# be ambiguous as to which entity it belongs to. We only enforce the per-entity domain
# when the query references exactly one status-bearing table (entity is unambiguous).
# Cross-entity collisions in ambiguous multi-table queries are NOT fully covered here;
# they fall back to the "valid in NO domain" check only. Closing that gap requires
# resolving each status_cd predicate to its source table after column binding, which
# is out of scope for this deterministic first pass.


def _collect_status_literals(ast: exp.Expression) -> list[str]:
    """Return string literals compared against a ``status_cd`` column.

    Handles both ``status_cd = 'X'`` / ``status_cd <> 'X'`` and
    ``status_cd IN ('X', 'Y')`` (and the qualified forms ``t.status_cd = ...``).
    Order-preserving and de-duplicated so error messages are deterministic.
    """
    literals: list[str] = []
    seen: set[str] = set()

    def _is_status_cd(node: exp.Expression | None) -> bool:
        return isinstance(node, exp.Column) and node.name.lower() == "status_cd"

    def _add(node: exp.Expression) -> None:
        if isinstance(node, exp.Literal) and node.is_string:
            value = node.this
            if value not in seen:
                seen.add(value)
                literals.append(value)

    for node in ast.walk():
        # status_cd = 'X', status_cd <> 'X', status_cd != 'X'
        if isinstance(node, (exp.EQ, exp.NEQ)):
            left, right = node.left, node.right
            if _is_status_cd(left):
                _add(right)
            elif _is_status_cd(right):
                _add(left)
        # status_cd IN ('X', 'Y', ...)
        elif isinstance(node, exp.In) and _is_status_cd(node.this):
            for value in node.expressions:
                _add(value)

    return literals


def _status_bearing_tables(ast: exp.Expression) -> set[str]:
    """Base tables referenced in the query that carry a governed status_cd domain."""
    tables: set[str] = set()
    for table in ast.find_all(exp.Table):
        name = table.name.lower()
        if name in _TABLE_ENTITY:
            tables.add(name)
    return tables


def _check_enums(ast: exp.Expression) -> list[str]:
    """Flag status_cd literals that violate the known status-code domains.

    Two tiers:
      * A literal valid in NO entity domain is always an error (e.g. 'INACTIVE').
      * If the query references exactly one status-bearing table, its entity_type is
        unambiguous, so a literal valid only in a *different* entity is also an error
        (e.g. 'ACTIVE' used against a loan-only query).
    """
    literals = _collect_status_literals(ast)
    if not literals:
        return []

    errors: list[str] = []
    tables = _status_bearing_tables(ast)

    # Unambiguous entity only when exactly one status-bearing table is in play.
    entity: str | None = None
    if len(tables) == 1:
        entity = _TABLE_ENTITY[next(iter(tables))]

    for literal in literals:
        upper = literal.upper()
        if upper not in _ALL_ENUM_VALUES:
            errors.append(
                f"Invalid status_cd value {literal!r}: not a valid status code in "
                f"any entity domain (members/accounts/loans/cards)."
            )
        elif entity is not None and upper not in _ENUM_DOMAINS[entity]:
            errors.append(
                f"Invalid status_cd value {literal!r} for {entity.lower()} query: "
                f"valid status codes for {entity} are "
                f"{sorted(_ENUM_DOMAINS[entity])}."
            )

    return errors


# --------------------------------------------------------------------------- #
# 2. Dialect / parse check
# --------------------------------------------------------------------------- #
# Tokens that signal a non-T-SQL dialect even though the tsql tokenizer/parser may
# accept them. T-SQL paginates with TOP / OFFSET..FETCH (never LIMIT) and casts with
# CAST(...) / CONVERT(...) (never the Postgres '::' operator). Detecting these at the
# token level ignores occurrences inside string literals automatically.
_FOREIGN_TOKENS: dict[TokenType, str] = {
    TokenType.LIMIT: (
        "LIMIT is not valid T-SQL (looks like Postgres/MySQL). "
        "Use TOP (n) or OFFSET ... FETCH NEXT ... ROWS ONLY."
    ),
    TokenType.DCOLON: (
        "'::' cast is not valid T-SQL (looks like Postgres). "
        "Use CAST(expr AS type) or CONVERT(type, expr)."
    ),
}


def _check_dialect_and_parse(sql: str) -> tuple[list[str], exp.Expression | None]:
    """Tokenize + parse as T-SQL. Returns (errors, ast). ast is None on hard failure.

    Runs BEFORE column binding so a dialect slip (a Postgres-ism) is reported as a
    dialect/parse error rather than surfacing later as a confusing binding failure.
    """
    # Token scan first: catches LIMIT / '::' even when the tsql parser is lenient
    # enough to build an AST from them.
    try:
        tokens = sqlglot.tokenize(sql, dialect=DIALECT)
    except (TokenError, SqlglotError) as exc:
        # Backticks and other illegal characters fail here.
        return [f"SQL failed to tokenize as T-SQL (dialect/syntax error): {exc}"], None

    for token in tokens:
        message = _FOREIGN_TOKENS.get(token.token_type)
        if message:
            return [message], None

    try:
        ast = sqlglot.parse_one(sql, dialect=DIALECT)
    except ParseError as exc:
        return [f"SQL failed to parse as T-SQL (dialect/syntax error): {exc}"], None
    except SqlglotError as exc:  # defensive: any other sqlglot-level failure
        return [f"SQL could not be parsed as T-SQL: {exc}"], None

    if ast is None:
        return ["SQL is empty or contains no parseable statement."], None

    return [], ast


# --------------------------------------------------------------------------- #
# 3. Column binding
# --------------------------------------------------------------------------- #
# An OptimizeError whose message matches one of these is a genuine column-binding
# failure (hard error). Anything else from qualify is downgraded to a warning so we
# never turn a valid query into a hard failure over a construct qualify can't handle.
_BINDING_ERROR_MARKERS = ("unknown column", "could not be resolved")


def _check_binding(
    ast: exp.Expression, catalog: dict[str, dict[str, str]]
) -> tuple[list[str], list[str]]:
    """Column-bind the AST against the catalog. Returns (errors, warnings).

    ``qualify`` raises ``OptimizeError`` on unknown / unresolvable columns
    (``validate_qualify_columns`` defaults to True). Those are hard errors. Other
    optimizer failures (constructs qualify legitimately trips on) become warnings.
    """
    try:
        # qualify mutates its argument in place, so hand it a copy — the enum check
        # runs on the original AST afterwards and must see it untouched.
        qualify(ast.copy(), schema=catalog, dialect=DIALECT)
    except OptimizeError as exc:
        message = str(exc)
        if any(marker in message.lower() for marker in _BINDING_ERROR_MARKERS):
            return [f"Column binding failed: {message}"], []
        # Unclassified optimizer trip → warn, don't hard-fail.
        return [], [f"Could not fully validate columns (optimizer warning): {message}"]
    except SqlglotError as exc:
        # Any other sqlglot-level issue during qualification is non-fatal.
        return [], [f"Could not fully validate columns (warning): {exc}"]

    return [], []


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #
def validate_sql(
    sql: str, catalog: dict[str, dict[str, str]] | None = None
) -> dict:
    """Validate a T-SQL draft offline against the schema_docs catalog.

    Returns ``{"ok": bool, "errors": [str], "warnings": [str]}``. ``ok`` is True only
    when there are no errors (warnings do not affect ``ok``).

    Pipeline, in deliberate order:
      1. Dialect / parse — reject Postgres-isms and unparseable SQL up front.
      2. Column binding — catch hallucinated / unresolvable columns.
      3. Enum domain — catch invalid status_cd literals.

    Steps 2 and 3 are skipped if step 1 already failed (no usable AST). Pass an
    explicit ``catalog`` to validate against a custom schema (e.g. in tests);
    otherwise it is built from ``schema_docs/*.md``.
    """
    errors: list[str] = []
    warnings: list[str] = []

    if not sql or not sql.strip():
        return {"ok": False, "errors": ["Empty SQL input."], "warnings": []}

    # Step 1: dialect / parse. Must come first so a dialect slip is classified here.
    dialect_errors, ast = _check_dialect_and_parse(sql)
    if dialect_errors or ast is None:
        return {"ok": False, "errors": dialect_errors, "warnings": warnings}

    if catalog is None:
        catalog = build_catalog()

    # Step 2: column binding.
    binding_errors, binding_warnings = _check_binding(ast, catalog)
    errors.extend(binding_errors)
    warnings.extend(binding_warnings)

    # Step 3: enum / status-code domain (independent of binding outcome).
    errors.extend(_check_enums(ast))

    return {"ok": not errors, "errors": errors, "warnings": warnings}
