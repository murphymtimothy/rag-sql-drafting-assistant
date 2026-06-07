"""
Extract MS SQL Server schema metadata into markdown docs compatible with the RAG pipeline.

REQUIRED PERMISSIONS (read-only SELECT on system catalog views only):
  GRANT SELECT ON INFORMATION_SCHEMA.TABLES TO <login>;
  GRANT SELECT ON INFORMATION_SCHEMA.COLUMNS TO <login>;
  GRANT VIEW DEFINITION TO <login>;   -- required for sys.* views and extended_properties

SETUP:
  Set SQL_SERVER_DSN environment variable before running:
    $env:SQL_SERVER_DSN = "DRIVER={ODBC Driver 17 for SQL Server};SERVER=myserver;DATABASE=mydb;UID=myuser;PWD=mypass;"
  Optionally set SQL_SERVER_SCHEMA (default: dbo):
    $env:SQL_SERVER_SCHEMA = "dbo"

OUTPUT:
  One .md file per table written to schema_docs/, using the same structure as the mock docs.
  Swapping mock → real is: run this script, then run `python ingest/build_index.py`.

MISSING DESCRIPTIONS:
  Columns/tables without MS_Description extended properties emit a
  '<!-- TODO: no description on file -->' placeholder. Grep for this
  in schema_docs/ to build a punch list of documentation gaps.
"""
import os
from pathlib import Path

try:
    import pyodbc
except ImportError as exc:
    raise ImportError(
        "pyodbc is required: pip install pyodbc. "
        "Also install the ODBC Driver 17 (or 18) for SQL Server from Microsoft."
    ) from exc

SCHEMA_DOCS = Path(__file__).parent.parent / "schema_docs"

_TABLES_SQL = """
SELECT
    t.TABLE_NAME,
    CAST(ep.value AS NVARCHAR(MAX)) AS table_description
FROM INFORMATION_SCHEMA.TABLES t
LEFT JOIN sys.extended_properties ep
    ON ep.major_id = OBJECT_ID(t.TABLE_SCHEMA + '.' + t.TABLE_NAME)
    AND ep.minor_id = 0
    AND ep.name = 'MS_Description'
    AND ep.class = 1
WHERE t.TABLE_TYPE = 'BASE TABLE'
  AND t.TABLE_SCHEMA = ?
ORDER BY t.TABLE_NAME
"""

_COLUMNS_SQL = """
SELECT
    c.COLUMN_NAME,
    c.DATA_TYPE,
    c.CHARACTER_MAXIMUM_LENGTH,
    c.NUMERIC_PRECISION,
    c.NUMERIC_SCALE,
    c.IS_NULLABLE,
    CAST(ep.value AS NVARCHAR(MAX)) AS column_description
FROM INFORMATION_SCHEMA.COLUMNS c
LEFT JOIN sys.extended_properties ep
    ON ep.major_id = OBJECT_ID(? + '.' + c.TABLE_NAME)
    AND ep.minor_id = c.ORDINAL_POSITION
    AND ep.name = 'MS_Description'
    AND ep.class = 1
WHERE c.TABLE_NAME = ?
  AND c.TABLE_SCHEMA = ?
ORDER BY c.ORDINAL_POSITION
"""

_PK_SQL = """
SELECT kcu.COLUMN_NAME
FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE kcu
    ON tc.CONSTRAINT_NAME = kcu.CONSTRAINT_NAME
    AND tc.TABLE_SCHEMA = kcu.TABLE_SCHEMA
WHERE tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
  AND kcu.TABLE_NAME = ?
  AND kcu.TABLE_SCHEMA = ?
ORDER BY kcu.ORDINAL_POSITION
"""

_FK_SQL = """
SELECT
    COL_NAME(fkc.parent_object_id, fkc.parent_column_id)   AS fk_column,
    OBJECT_NAME(fkc.referenced_object_id)                   AS ref_table,
    COL_NAME(fkc.referenced_object_id, fkc.referenced_column_id) AS ref_column
FROM sys.foreign_keys fk
JOIN sys.foreign_key_columns fkc ON fk.object_id = fkc.constraint_object_id
WHERE OBJECT_NAME(fk.parent_object_id) = ?
ORDER BY fk_column
"""


def _fmt_type(row) -> str:
    dtype = row.DATA_TYPE.upper()
    if row.CHARACTER_MAXIMUM_LENGTH:
        length = "MAX" if row.CHARACTER_MAXIMUM_LENGTH == -1 else row.CHARACTER_MAXIMUM_LENGTH
        return f"{dtype}({length})"
    if row.NUMERIC_PRECISION is not None and row.NUMERIC_SCALE is not None:
        return f"{dtype}({row.NUMERIC_PRECISION},{row.NUMERIC_SCALE})"
    return dtype


def _render_table(cursor, schema: str, table_name: str, table_desc: str | None) -> str:
    cursor.execute(_COLUMNS_SQL, (schema, table_name, schema))
    columns = cursor.fetchall()

    cursor.execute(_PK_SQL, (table_name, schema))
    pks = [r.COLUMN_NAME for r in cursor.fetchall()]

    cursor.execute(_FK_SQL, (table_name,))
    fks = cursor.fetchall()

    desc = table_desc or "<!-- TODO: no description on file -->"

    lines = [
        f"# TABLE: {table_name}",
        "",
        "**Subject area:** <!-- TODO: classify subject area -->",
        f"**Purpose:** {desc}",
        "",
        "## Columns",
        "",
        "| Column | Type | Nullable | Description | Example |",
        "|---|---|---|---|---|",
    ]

    for col in columns:
        col_desc = str(col.column_description) if col.column_description else "<!-- TODO: no description on file -->"
        nullable = "NOT NULL" if col.IS_NULLABLE == "NO" else "NULL"
        lines.append(f"| {col.COLUMN_NAME} | {_fmt_type(col)} | {nullable} | {col_desc} | — |")

    lines += [
        "",
        "## Primary key",
        ", ".join(pks) if pks else "<!-- TODO: no primary key found -->",
        "",
        "## Foreign keys / relationships",
    ]

    if fks:
        for fk in fks:
            lines.append(f"- `{fk.fk_column}` → `{fk.ref_table}.{fk.ref_column}`")
    else:
        lines.append("*(none)*")

    lines += ["", "## Naming conventions", "*(add any table-level naming conventions here)*", ""]
    return "\n".join(lines)


def extract_all(dsn: str, schema: str = "dbo", output_dir: Path = SCHEMA_DOCS) -> int:
    """Connect to SQL Server, extract all tables in schema, write one .md per table."""
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Connecting to SQL Server (schema={schema})...")
    conn = pyodbc.connect(dsn, timeout=30)
    cursor = conn.cursor()

    cursor.execute(_TABLES_SQL, (schema,))
    tables = cursor.fetchall()
    print(f"Found {len(tables)} tables in schema '{schema}'.")

    for row in tables:
        content = _render_table(cursor, schema, row.TABLE_NAME, row.table_description)
        out_path = output_dir / f"{row.TABLE_NAME}.md"
        out_path.write_text(content, encoding="utf-8")
        print(f"  wrote {out_path.name}")

    conn.close()
    return len(tables)


if __name__ == "__main__":
    dsn = os.environ.get("SQL_SERVER_DSN")
    if not dsn:
        raise SystemExit(
            "Set SQL_SERVER_DSN before running.\n"
            "Example:\n"
            "  $env:SQL_SERVER_DSN = \"DRIVER={ODBC Driver 17 for SQL Server};"
            "SERVER=myserver;DATABASE=mydw;UID=readonly_user;PWD=mypass;\"\n"
            "\nOptionally set SQL_SERVER_SCHEMA (default: dbo):\n"
            "  $env:SQL_SERVER_SCHEMA = \"dbo\""
        )
    schema = os.environ.get("SQL_SERVER_SCHEMA", "dbo")
    count = extract_all(dsn, schema)
    print(f"\nDone. {count} tables extracted to {SCHEMA_DOCS}/")
    print("Next step: python ingest/build_index.py")
