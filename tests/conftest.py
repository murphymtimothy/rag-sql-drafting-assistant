from pathlib import Path
import pytest

SCHEMA_DOCS = Path(__file__).parent.parent / "schema_docs"


@pytest.fixture
def schema_docs_path():
    return SCHEMA_DOCS


@pytest.fixture
def minimal_schema_docs(tmp_path):
    """Two minimal schema doc files for unit tests that need a schema_docs directory."""
    (tmp_path / "members.md").write_text(
        "# TABLE: members\n\n**Subject area:** Member/party\n**Purpose:** Core member record.\n\n"
        "## Columns\n\n| Column | Type | Nullable | Description | Example |\n|---|---|---|---|---|\n"
        "| member_id | INT | NOT NULL | Primary key | 10042 |\n"
        "| first_name | VARCHAR(100) | NOT NULL | First name | Jane |\n"
        "| status_cd | VARCHAR(10) | NOT NULL | Member status | ACTIVE |\n\n"
        "## Primary key\nmember_id\n\n## Foreign keys / relationships\n"
        "- `status_cd` → `ref_status_codes.status_cd`\n",
        encoding="utf-8",
    )
    (tmp_path / "loans.md").write_text(
        "# TABLE: loans\n\n**Subject area:** Lending\n**Purpose:** Approved loan records.\n\n"
        "## Columns\n\n| Column | Type | Nullable | Description | Example |\n|---|---|---|---|---|\n"
        "| loan_id | INT | NOT NULL | Primary key | 5001 |\n"
        "| member_id | INT | NOT NULL | FK to members | 10042 |\n"
        "| days_past_due | INT | NOT NULL | 0 = current | 0 |\n\n"
        "## Primary key\nloan_id\n\n## Foreign keys / relationships\n"
        "- `member_id` → `members.member_id`\n",
        encoding="utf-8",
    )
    return tmp_path
