# SQL-Drafting Assistant POC Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Update (2026-06-08):** This is the original implementation plan. The default model was later changed from `gpt-oss:20b` to **`qwen2.5-coder:7b`** following a five-model evaluation (see [`docs/model-selection.md`](model-selection.md)), and the assistant added a Microsoft SQL Server (T-SQL) dialect instruction plus a `reasoning_effort` guard for reasoning-style models. Model names below were updated to match; embedded code listings are otherwise preserved as the historical plan.

**Goal:** Build a fully local SQL-drafting assistant grounded via RAG over a mock credit-union warehouse schema, with automated grounding evaluation, structured logging, and a scheduled schema-refresh pipeline.

**Architecture:** LlamaIndex + ChromaDB for ingestion (reuses proven §13 pattern); hand-rolled retrieval → prompt → generation → citation → logging for full transparency. Eval harness runs every question RAG-on vs. RAG-off and scores grounding automatically. Refresh scheduler hashes schema docs on a configurable interval and rebuilds the index only when changes are detected.

**Tech Stack:** Python 3.11+, Ollama (`qwen2.5-coder:7b` + `nomic-embed-text`), LlamaIndex 0.10+, ChromaDB, OpenAI Python SDK (pointed at Ollama), PyYAML, pyodbc, pytest

---

## File Map

```
poc-sql-assistant/
├── pyproject.toml                              create  — package + pytest config
├── requirements.txt                            create  — pinned deps
├── .gitignore                                  create
├── schema_docs/                                create  — 20 markdown files (Tasks 2-3)
│   ├── members.md ... ref_status_codes.md
├── ingest/
│   ├── __init__.py                             create
│   └── build_index.py                          create  — chunk→embed→persist
├── assistant/
│   ├── __init__.py                             create
│   └── sql_assistant.py                        create  — answer_question() + log_result() + CLI
├── eval/
│   ├── __init__.py                             create
│   ├── checker.py                              create  — grounding checker
│   ├── test_questions.yaml                     create  — 15 curated questions
│   └── run_eval.py                             create  — RAG-on/off batch runner + report
├── refresh/
│   ├── __init__.py                             create
│   └── refresh_scheduler.py                    create  — hash-detect + reindex + scheduler
├── extraction/
│   ├── __init__.py                             create
│   └── extract_schema_from_sqlserver.py        create  — real DB → markdown docs
├── logs/
│   └── .gitkeep                                create
└── tests/
    ├── conftest.py                             create  — shared fixtures
    ├── test_checker.py                         create  — unit tests (no external deps)
    ├── test_sql_assistant.py                   create  — unit tests (mocked Ollama + Chroma)
    └── test_refresh.py                         create  — unit tests (file-system only)
```

**Key interfaces locked in across all tasks:**

```python
# assistant/sql_assistant.py
def answer_question(
    question: str,
    rag_enabled: bool = True,
    model: str = "qwen2.5-coder:7b",
    k: int = 5,
    chroma_path: Path = CHROMA_PATH,
) -> dict:
    # returns: {timestamp, question, rag_enabled, sql, explanation,
    #           citations, raw_chunks, chunk_count, latency_ms, model,
    #           eval_score, eval_reason}

def log_result(result: dict, logs_path: Path = LOGS_PATH) -> None:
    # appends one JSON record to logs_path (omits raw_chunks to keep log compact)

# ingest/build_index.py
def build_index(schema_docs_path: Path, chroma_path: Path) -> int:
    # returns chunk count

# eval/checker.py
def check_answer(
    result: dict,
    expected_tables: list[str],
    expected_columns: list[str],
    schema_docs: Path = SCHEMA_DOCS,
) -> dict:
    # returns: {"score": float, "reason": str}

# refresh/refresh_scheduler.py
def run_refresh_cycle(
    schema_docs: Path,
    chroma_path: Path,
    state_file: Path,
    refresh_log: Path,
) -> str:
    # returns "reindexed" or "skipped"
```

---

## Task 1: Project bootstrap

**Files:**
- Create: `poc-sql-assistant/pyproject.toml`
- Create: `poc-sql-assistant/requirements.txt`
- Create: `poc-sql-assistant/.gitignore`
- Create: `poc-sql-assistant/logs/.gitkeep`
- Create: `poc-sql-assistant/ingest/__init__.py`
- Create: `poc-sql-assistant/assistant/__init__.py`
- Create: `poc-sql-assistant/eval/__init__.py`
- Create: `poc-sql-assistant/refresh/__init__.py`
- Create: `poc-sql-assistant/extraction/__init__.py`
- Create: `poc-sql-assistant/tests/conftest.py`

- [ ] **Step 1: Create the project directory and all subdirectories**

```powershell
mkdir poc-sql-assistant
cd poc-sql-assistant
mkdir schema_docs, ingest, assistant, eval, refresh, extraction, logs, tests
```

- [ ] **Step 2: Create `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=64"]
build-backend = "setuptools.backends.legacy:build"

[project]
name = "poc-sql-assistant"
version = "0.1.0"
requires-python = ">=3.11"

[tool.setuptools.packages.find]
where = ["."]
include = ["ingest*", "assistant*", "eval*", "refresh*", "extraction*"]

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
markers = ["integration: requires Ollama running (set OLLAMA_RUNNING=1)"]
```

- [ ] **Step 3: Create `requirements.txt`**

```
llama-index>=0.10.0,<0.12
llama-index-llms-ollama
llama-index-embeddings-ollama
llama-index-vector-stores-chroma
chromadb>=0.5.0
openai>=1.0.0
pyyaml>=6.0
pyodbc>=5.0
pytest>=8.0
pytest-mock>=3.0
```

- [ ] **Step 4: Create `.gitignore`**

```
chroma_db/
logs/*.jsonl
logs/*.json
logs/*.md
__pycache__/
*.pyc
.venv/
```

- [ ] **Step 5: Create empty `__init__.py` files and `logs/.gitkeep`**

```powershell
"" | Out-File ingest/__init__.py -Encoding utf8
"" | Out-File assistant/__init__.py -Encoding utf8
"" | Out-File eval/__init__.py -Encoding utf8
"" | Out-File refresh/__init__.py -Encoding utf8
"" | Out-File extraction/__init__.py -Encoding utf8
"" | Out-File logs/.gitkeep -Encoding utf8
```

- [ ] **Step 6: Create `tests/conftest.py`**

```python
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
        "## Primary key\nmember_id\n\n## Foreign keys / relationships\n- `status_cd` → `ref_status_codes.status_cd`\n",
        encoding="utf-8",
    )
    (tmp_path / "loans.md").write_text(
        "# TABLE: loans\n\n**Subject area:** Lending\n**Purpose:** Approved loan records.\n\n"
        "## Columns\n\n| Column | Type | Nullable | Description | Example |\n|---|---|---|---|---|\n"
        "| loan_id | INT | NOT NULL | Primary key | 5001 |\n"
        "| member_id | INT | NOT NULL | FK to members | 10042 |\n"
        "| days_past_due | INT | NOT NULL | 0 = current | 0 |\n\n"
        "## Primary key\nloan_id\n\n## Foreign keys / relationships\n- `member_id` → `members.member_id`\n",
        encoding="utf-8",
    )
    return tmp_path
```

- [ ] **Step 7: Install dependencies**

```powershell
pip install -r requirements.txt
```

- [ ] **Step 8: Verify pytest discovers tests (empty run — should show 0 tests)**

```powershell
pytest -v
```

Expected output: `no tests ran` (or 0 collected). If you see import errors, check that the `pythonpath = ["."]` in `pyproject.toml` is correct.

- [ ] **Step 9: Commit**

```powershell
git init
git add pyproject.toml requirements.txt .gitignore logs/.gitkeep ingest/__init__.py assistant/__init__.py eval/__init__.py refresh/__init__.py extraction/__init__.py tests/conftest.py
git commit -m "feat: bootstrap poc-sql-assistant project structure"
```

---

## Task 2: Schema docs — Member/Party + Deposits (8 tables)

**Files:** Create all files in `poc-sql-assistant/schema_docs/`

These are plain markdown — no TDD cycle, just create each file and verify the format is consistent.

- [ ] **Step 1: Create `schema_docs/members.md`**

```markdown
# TABLE: members

**Subject area:** Member/party
**Purpose:** Core member record — one row per individual member of the credit union.

## Columns

| Column | Type | Nullable | Description | Example |
|---|---|---|---|---|
| member_id | INT | NOT NULL | Surrogate primary key, auto-incremented | 10042 |
| first_name | VARCHAR(100) | NOT NULL | Legal first name | Jane |
| last_name | VARCHAR(100) | NOT NULL | Legal last name | Kowalski |
| date_of_birth | DATE | NOT NULL | Member date of birth | 1985-04-12 |
| member_since_date | DATE | NOT NULL | Date the member joined the credit union | 2014-09-01 |
| status_cd | VARCHAR(10) | NOT NULL | Current membership status; resolves against ref_status_codes (entity_type='MEMBER') | ACTIVE |
| ssn_last4 | CHAR(4) | NOT NULL | Last four digits of SSN (fictional, never full SSN) | 6712 |

## Primary key
member_id

## Foreign keys / relationships
- `status_cd` → `ref_status_codes.status_cd` (filter entity_type = 'MEMBER')

## Naming conventions
- `_cd` suffix indicates a code that resolves against a reference table.
- `_date` suffix indicates a calendar date (DATE type, no time component).
```

- [ ] **Step 2: Create `schema_docs/addresses.md`**

```markdown
# TABLE: addresses

**Subject area:** Member/party
**Purpose:** Mailing and physical addresses for members; supports multiple address types and historical address records via effective/end dates.

## Columns

| Column | Type | Nullable | Description | Example |
|---|---|---|---|---|
| address_id | INT | NOT NULL | Surrogate primary key | 88001 |
| member_id | INT | NOT NULL | FK — the member this address belongs to | 10042 |
| address_type_cd | VARCHAR(10) | NOT NULL | PRIMARY, MAILING, or SEASONAL | PRIMARY |
| street1 | VARCHAR(200) | NOT NULL | First line of street address | 742 Evergreen Terrace |
| street2 | VARCHAR(200) | NULL | Apartment, suite, unit (optional) | Apt 3B |
| city | VARCHAR(100) | NOT NULL | City | Springfield |
| state_cd | CHAR(2) | NOT NULL | Two-letter US state code | IL |
| zip | CHAR(5) | NOT NULL | Five-digit ZIP code | 62701 |
| effective_date | DATE | NOT NULL | Date this address became active | 2021-03-15 |
| end_date | DATE | NULL | Date this address ended; NULL means currently active | NULL |

## Primary key
address_id

## Foreign keys / relationships
- `member_id` → `members.member_id`

## Naming conventions
- To get the current address: filter WHERE end_date IS NULL.
- `state_cd` is always uppercase two-letter USPS abbreviation.
```

- [ ] **Step 3: Create `schema_docs/contact_info.md`**

```markdown
# TABLE: contact_info

**Subject area:** Member/party
**Purpose:** Phone numbers and email addresses for members, including consent flags required for TCPA and email marketing compliance.

## Columns

| Column | Type | Nullable | Description | Example |
|---|---|---|---|---|
| contact_id | INT | NOT NULL | Surrogate primary key | 55201 |
| member_id | INT | NOT NULL | FK — the member this contact belongs to | 10042 |
| contact_type_cd | VARCHAR(15) | NOT NULL | PHONE_MOBILE, PHONE_HOME, PHONE_WORK, EMAIL | PHONE_MOBILE |
| contact_value | VARCHAR(255) | NOT NULL | The phone number or email address | 217-555-0183 |
| is_primary | BIT | NOT NULL | 1 if this is the member's preferred contact of this type | 1 |
| is_consent_given | BIT | NOT NULL | 1 if the member has consented to contact at this address/number | 1 |

## Primary key
contact_id

## Foreign keys / relationships
- `member_id` → `members.member_id`

## Naming conventions
- `is_` prefix indicates a boolean flag stored as BIT (0/1).
```

- [ ] **Step 4: Create `schema_docs/household_relationships.md`**

```markdown
# TABLE: household_relationships

**Subject area:** Member/party
**Purpose:** Tracks relationships between members, such as joint ownership, beneficiary designations, and power-of-attorney arrangements.

## Columns

| Column | Type | Nullable | Description | Example |
|---|---|---|---|---|
| relationship_id | INT | NOT NULL | Surrogate primary key | 3301 |
| member_id_primary | INT | NOT NULL | FK — the primary member in the relationship | 10042 |
| member_id_related | INT | NOT NULL | FK — the related member (e.g., the beneficiary or joint owner) | 10043 |
| relationship_type_cd | VARCHAR(20) | NOT NULL | JOINT_OWNER, BENEFICIARY, POA, DEPENDENT | JOINT_OWNER |
| effective_date | DATE | NOT NULL | Date the relationship became effective | 2019-06-01 |

## Primary key
relationship_id

## Foreign keys / relationships
- `member_id_primary` → `members.member_id`
- `member_id_related` → `members.member_id`
```

- [ ] **Step 5: Create `schema_docs/accounts.md`**

```markdown
# TABLE: accounts

**Subject area:** Deposits
**Purpose:** Deposit accounts (checking, savings, money market, CDs) held by members; one row per account.

## Columns

| Column | Type | Nullable | Description | Example |
|---|---|---|---|---|
| account_id | INT | NOT NULL | Surrogate primary key | 20100 |
| member_id | INT | NOT NULL | FK — the member who owns this account | 10042 |
| account_type_cd | VARCHAR(10) | NOT NULL | FK — type of account; resolves against account_types | CHECKING |
| opened_date | DATE | NOT NULL | Date the account was opened | 2014-09-01 |
| closed_date | DATE | NULL | Date the account was closed; NULL = still open | NULL |
| status_cd | VARCHAR(10) | NOT NULL | Current account status; resolves against ref_status_codes (entity_type='ACCOUNT') | ACTIVE |
| current_balance | DECIMAL(15,2) | NOT NULL | Ledger balance at end of last posting cycle | 4821.33 |
| available_balance | DECIMAL(15,2) | NOT NULL | Ledger balance minus any active holds | 4621.33 |

## Primary key
account_id

## Foreign keys / relationships
- `member_id` → `members.member_id`
- `account_type_cd` → `account_types.account_type_cd`
- `status_cd` → `ref_status_codes.status_cd` (filter entity_type = 'ACCOUNT')

## Naming conventions
- available_balance = current_balance minus sum of active holds.amount from the holds table.
```

- [ ] **Step 6: Create `schema_docs/account_types.md`**

```markdown
# TABLE: account_types

**Subject area:** Deposits
**Purpose:** Reference table defining the types of deposit accounts offered (e.g., Checking, Regular Savings, Money Market, Certificate of Deposit).

## Columns

| Column | Type | Nullable | Description | Example |
|---|---|---|---|---|
| account_type_cd | VARCHAR(10) | NOT NULL | Short code used as the primary key and FK target | CHECKING |
| account_type_name | VARCHAR(100) | NOT NULL | Human-readable name | Basic Checking |
| is_dividend_bearing | BIT | NOT NULL | 1 if dividends/interest are paid on this account type | 0 |
| min_balance | DECIMAL(15,2) | NOT NULL | Minimum balance required to avoid fees | 0.00 |
| description | VARCHAR(500) | NULL | Long description of account features | NULL |

## Primary key
account_type_cd

## Foreign keys / relationships
*(none — this is a reference/lookup table)*
```

- [ ] **Step 7: Create `schema_docs/transactions.md`**

```markdown
# TABLE: transactions

**Subject area:** Deposits
**Purpose:** Individual debit/credit postings to deposit accounts, including fee assessments, dividend credits, and hold releases.

## Columns

| Column | Type | Nullable | Description | Example |
|---|---|---|---|---|
| transaction_id | INT | NOT NULL | Surrogate primary key | 9900441 |
| account_id | INT | NOT NULL | FK — the account this transaction posted to | 20100 |
| transaction_date | DATETIME | NOT NULL | Date and time the transaction posted | 2026-05-15 14:32:00 |
| transaction_type_cd | VARCHAR(10) | NOT NULL | DEBIT, CREDIT, FEE, DIVIDEND, HOLD_RELEASE | DEBIT |
| amount | DECIMAL(15,2) | NOT NULL | Transaction amount — always positive; direction indicated by transaction_type_cd | 52.00 |
| running_balance | DECIMAL(15,2) | NOT NULL | Account ledger balance immediately after this transaction posted | 4769.33 |
| channel_cd | VARCHAR(10) | NOT NULL | Channel through which the transaction was initiated; resolves against ref_channel_codes | BRANCH |
| description | VARCHAR(500) | NULL | Memo or description from originating system | DEBIT CARD PURCHASE |
| teller_id | INT | NULL | FK to staff.staff_id for branch-initiated transactions; NULL for digital/ATM | 201 |

## Primary key
transaction_id

## Foreign keys / relationships
- `account_id` → `accounts.account_id`
- `channel_cd` → `ref_channel_codes.channel_cd`
- `teller_id` → `staff.staff_id` (NULL for non-branch transactions)
```

- [ ] **Step 8: Create `schema_docs/holds.md`**

```markdown
# TABLE: holds

**Subject area:** Deposits
**Purpose:** Active and historical holds placed on deposit accounts, reducing available balance without affecting ledger balance.

## Columns

| Column | Type | Nullable | Description | Example |
|---|---|---|---|---|
| hold_id | INT | NOT NULL | Surrogate primary key | 77002 |
| account_id | INT | NOT NULL | FK — the account the hold is placed on | 20100 |
| hold_type_cd | VARCHAR(10) | NOT NULL | CHECK_HOLD, ADMIN_HOLD, REGULATORY | CHECK_HOLD |
| amount | DECIMAL(15,2) | NOT NULL | Dollar amount of the hold | 200.00 |
| placed_date | DATETIME | NOT NULL | Date and time the hold was placed | 2026-06-01 09:15:00 |
| release_date | DATETIME | NULL | Date and time the hold was released; NULL = still active | NULL |
| reason | VARCHAR(500) | NULL | Reason for the hold | Deposited check pending clearance |

## Primary key
hold_id

## Foreign keys / relationships
- `account_id` → `accounts.account_id`

## Naming conventions
- Active holds: filter WHERE release_date IS NULL.
- Sum of active holds = accounts.current_balance - accounts.available_balance.
```

- [ ] **Step 9: Verify all 8 files exist and follow consistent structure**

```powershell
Get-ChildItem schema_docs/ -Filter *.md | Select-Object Name
```

Expected: 8 files listed (members, addresses, contact_info, household_relationships, accounts, account_types, transactions, holds).

- [ ] **Step 10: Commit**

```powershell
git add schema_docs/
git commit -m "feat: add member/party and deposits schema docs (8 tables)"
```

---

## Task 3: Schema docs — Lending + Cards + Branch/Channel (12 tables)

**Files:** Continue adding to `poc-sql-assistant/schema_docs/`

- [ ] **Step 1: Create `schema_docs/loan_applications.md`**

```markdown
# TABLE: loan_applications

**Subject area:** Lending
**Purpose:** Records each loan application submitted by a member, from submission through credit decision.

## Columns

| Column | Type | Nullable | Description | Example |
|---|---|---|---|---|
| application_id | INT | NOT NULL | Surrogate primary key | 6001 |
| member_id | INT | NOT NULL | FK — the applying member | 10042 |
| loan_type_cd | VARCHAR(10) | NOT NULL | Type of loan requested; resolves against loan_types | AUTO |
| requested_amount | DECIMAL(15,2) | NOT NULL | Amount requested by the member | 18500.00 |
| application_date | DATE | NOT NULL | Date the application was submitted | 2025-11-03 |
| decision_date | DATE | NULL | Date a credit decision was made; NULL = pending | 2025-11-05 |
| decision_cd | VARCHAR(10) | NULL | APPROVED, DENIED, WITHDRAWN, PENDING | APPROVED |
| denied_reason_cd | VARCHAR(20) | NULL | Reason code if denied; NULL otherwise | NULL |

## Primary key
application_id

## Foreign keys / relationships
- `member_id` → `members.member_id`
- `loan_type_cd` → `loan_types.loan_type_cd`
```

- [ ] **Step 2: Create `schema_docs/loans.md`**

```markdown
# TABLE: loans

**Subject area:** Lending
**Purpose:** Active and closed loans — one row per approved, funded loan. Created from an approved loan_application.

## Columns

| Column | Type | Nullable | Description | Example |
|---|---|---|---|---|
| loan_id | INT | NOT NULL | Surrogate primary key | 5001 |
| application_id | INT | NOT NULL | FK — the application this loan originated from | 6001 |
| member_id | INT | NOT NULL | FK — the borrowing member | 10042 |
| loan_type_cd | VARCHAR(10) | NOT NULL | FK — type of loan; resolves against loan_types | AUTO |
| principal_amount | DECIMAL(15,2) | NOT NULL | Original funded loan amount | 18500.00 |
| interest_rate | DECIMAL(5,4) | NOT NULL | Annual interest rate as a decimal (e.g., 0.0549 = 5.49%) | 0.0549 |
| term_months | INT | NOT NULL | Loan term in months | 60 |
| origination_date | DATE | NOT NULL | Date the loan was funded | 2025-11-07 |
| maturity_date | DATE | NOT NULL | Scheduled payoff date | 2030-11-07 |
| status_cd | VARCHAR(10) | NOT NULL | Current loan status; resolves against ref_status_codes (entity_type='LOAN') | CURRENT |

## Primary key
loan_id

## Foreign keys / relationships
- `application_id` → `loan_applications.application_id`
- `member_id` → `members.member_id`
- `loan_type_cd` → `loan_types.loan_type_cd`
- `status_cd` → `ref_status_codes.status_cd` (filter entity_type = 'LOAN')

## Naming conventions
- interest_rate is stored as a decimal fraction, not a percentage string.
- For delinquency status and days_past_due, join to loan_status_history (current row: end_date IS NULL).
```

- [ ] **Step 3: Create `schema_docs/loan_types.md`**

```markdown
# TABLE: loan_types

**Subject area:** Lending
**Purpose:** Reference table of loan product types offered (e.g., Auto, Personal, HELOC, Mortgage, Credit Builder).

## Columns

| Column | Type | Nullable | Description | Example |
|---|---|---|---|---|
| loan_type_cd | VARCHAR(10) | NOT NULL | Short code — primary key and FK target | AUTO |
| loan_type_name | VARCHAR(100) | NOT NULL | Human-readable name | Auto Loan |
| max_ltv | DECIMAL(5,4) | NULL | Maximum loan-to-value ratio; NULL if not collateral-based | 0.9000 |
| max_term_months | INT | NOT NULL | Maximum allowable term in months | 84 |
| is_secured | BIT | NOT NULL | 1 if the loan requires collateral | 1 |

## Primary key
loan_type_cd

## Foreign keys / relationships
*(none — reference/lookup table)*
```

- [ ] **Step 4: Create `schema_docs/payment_schedules.md`**

```markdown
# TABLE: payment_schedules

**Subject area:** Lending
**Purpose:** Amortization schedule for each loan — one row per scheduled payment, tracking whether each payment has been made.

## Columns

| Column | Type | Nullable | Description | Example |
|---|---|---|---|---|
| schedule_id | INT | NOT NULL | Surrogate primary key | 301001 |
| loan_id | INT | NOT NULL | FK — the loan this payment belongs to | 5001 |
| due_date | DATE | NOT NULL | Scheduled payment due date | 2026-01-07 |
| payment_amount | DECIMAL(15,2) | NOT NULL | Total scheduled payment | 349.83 |
| principal_portion | DECIMAL(15,2) | NOT NULL | Portion applied to principal reduction | 264.90 |
| interest_portion | DECIMAL(15,2) | NOT NULL | Portion applied to interest | 84.93 |
| is_paid | BIT | NOT NULL | 1 if payment has been received | 1 |
| paid_date | DATE | NULL | Actual date payment was received; NULL if not yet paid | 2026-01-05 |

## Primary key
schedule_id

## Foreign keys / relationships
- `loan_id` → `loans.loan_id`

## Naming conventions
- payment_amount = principal_portion + interest_portion (no escrow in this schema).
- To find missed payments: WHERE is_paid = 0 AND due_date < GETDATE().
```

- [ ] **Step 5: Create `schema_docs/loan_status_history.md`**

```markdown
# TABLE: loan_status_history

**Subject area:** Lending
**Purpose:** Time-series delinquency and status tracking for loans. One row per status period. The current status row has end_date IS NULL. Use days_past_due to determine delinquency bucket (0=current, 1-29=1-29 DPD, 30+=30+ DPD).

## Columns

| Column | Type | Nullable | Description | Example |
|---|---|---|---|---|
| status_id | INT | NOT NULL | Surrogate primary key | 800441 |
| loan_id | INT | NOT NULL | FK — the loan being tracked | 5001 |
| status_cd | VARCHAR(10) | NOT NULL | CURRENT, DLQ_30, DLQ_60, DLQ_90, CHARGE_OFF, PAID_OFF; resolves against ref_status_codes (entity_type='LOAN') | CURRENT |
| days_past_due | INT | NOT NULL | Number of days past due at the time this status was recorded; 0 = current | 0 |
| effective_date | DATE | NOT NULL | Date this status period began | 2026-06-01 |
| end_date | DATE | NULL | Date this status period ended; NULL = currently active status | NULL |
| recorded_by | INT | NOT NULL | FK — staff member who recorded this status change | 201 |

## Primary key
status_id

## Foreign keys / relationships
- `loan_id` → `loans.loan_id`
- `status_cd` → `ref_status_codes.status_cd` (filter entity_type = 'LOAN')
- `recorded_by` → `staff.staff_id`

## Naming conventions
- Current status: WHERE end_date IS NULL. There should be exactly one current row per loan.
- Delinquency bucket: 0 DPD = current; 1–29 = early delinquency; 30–59 = 30 DPD; 60–89 = 60 DPD; 90+ = serious delinquency.
```

- [ ] **Step 6: Create `schema_docs/card_accounts.md`**

```markdown
# TABLE: card_accounts

**Subject area:** Cards
**Purpose:** Credit card accounts held by members — one row per card account.

## Columns

| Column | Type | Nullable | Description | Example |
|---|---|---|---|---|
| card_account_id | INT | NOT NULL | Surrogate primary key | 40001 |
| member_id | INT | NOT NULL | FK — the member who holds this card | 10042 |
| card_type_cd | VARCHAR(15) | NOT NULL | VISA_CLASSIC, VISA_PLATINUM, SECURED | VISA_PLATINUM |
| credit_limit | DECIMAL(15,2) | NOT NULL | Authorized credit limit | 5000.00 |
| available_credit | DECIMAL(15,2) | NOT NULL | Credit limit minus current balance | 3241.50 |
| opened_date | DATE | NOT NULL | Date the card account was opened | 2020-02-14 |
| status_cd | VARCHAR(10) | NOT NULL | Current card status; resolves against ref_status_codes (entity_type='CARD') | ACTIVE |

## Primary key
card_account_id

## Foreign keys / relationships
- `member_id` → `members.member_id`
- `status_cd` → `ref_status_codes.status_cd` (filter entity_type = 'CARD')
```

- [ ] **Step 7: Create `schema_docs/card_transactions.md`**

```markdown
# TABLE: card_transactions

**Subject area:** Cards
**Purpose:** Individual card purchase, payment, and refund transactions posted to card accounts.

## Columns

| Column | Type | Nullable | Description | Example |
|---|---|---|---|---|
| card_txn_id | INT | NOT NULL | Surrogate primary key | 7700881 |
| card_account_id | INT | NOT NULL | FK — the card account this transaction posted to | 40001 |
| txn_date | DATETIME | NOT NULL | Date and time the transaction posted | 2026-05-20 13:44:00 |
| merchant_name | VARCHAR(255) | NOT NULL | Merchant name from the card network | SPRINGFIELD GROCER |
| merchant_category_cd | CHAR(4) | NOT NULL | ISO MCC code (e.g., 5411 = Grocery Stores) | 5411 |
| amount | DECIMAL(15,2) | NOT NULL | Transaction amount — always positive | 87.54 |
| is_credit | BIT | NOT NULL | 0 = purchase/charge; 1 = payment or refund | 0 |
| channel_cd | VARCHAR(10) | NOT NULL | Channel used; resolves against ref_channel_codes | CARD_PRESENT |

## Primary key
card_txn_id

## Foreign keys / relationships
- `card_account_id` → `card_accounts.card_account_id`
- `channel_cd` → `ref_channel_codes.channel_cd`
```

- [ ] **Step 8: Create `schema_docs/card_rewards.md`**

```markdown
# TABLE: card_rewards

**Subject area:** Cards
**Purpose:** Reward point ledger for card accounts — one row per point-earning or point-redemption event. Points balance is tracked as a running total.

## Columns

| Column | Type | Nullable | Description | Example |
|---|---|---|---|---|
| reward_id | INT | NOT NULL | Surrogate primary key | 9900001 |
| card_account_id | INT | NOT NULL | FK — the card account these points belong to | 40001 |
| transaction_date | DATE | NOT NULL | Date the point event occurred | 2026-05-20 |
| points_earned | INT | NOT NULL | Points earned in this event; 0 for redemption-only rows | 87 |
| points_redeemed | INT | NOT NULL | Points redeemed in this event; 0 for earn-only rows | 0 |
| points_balance | INT | NOT NULL | Running points balance after this event | 4321 |
| expiry_date | DATE | NULL | Date points expire; NULL means points do not expire | NULL |

## Primary key
reward_id

## Foreign keys / relationships
- `card_account_id` → `card_accounts.card_account_id`

## Naming conventions
- To get the current points balance for a card: SELECT TOP 1 points_balance ORDER BY transaction_date DESC, reward_id DESC.
- Points are issued at 1 point per dollar of purchases (is_credit=0 card_transactions).
```

- [ ] **Step 9: Create `schema_docs/branches.md`**

```markdown
# TABLE: branches

**Subject area:** Branch/channel
**Purpose:** Physical branch locations operated by the credit union.

## Columns

| Column | Type | Nullable | Description | Example |
|---|---|---|---|---|
| branch_id | INT | NOT NULL | Surrogate primary key | 10 |
| branch_name | VARCHAR(200) | NOT NULL | Display name of the branch | Downtown Springfield Branch |
| address_id | INT | NOT NULL | FK — physical address of the branch | 88099 |
| phone | VARCHAR(20) | NOT NULL | Main branch phone number | 217-555-0100 |
| opened_date | DATE | NOT NULL | Date the branch opened | 2001-03-01 |
| is_active | BIT | NOT NULL | 1 if the branch is currently open | 1 |

## Primary key
branch_id

## Foreign keys / relationships
- `address_id` → `addresses.address_id`
```

- [ ] **Step 10: Create `schema_docs/staff.md`**

```markdown
# TABLE: staff

**Subject area:** Branch/channel
**Purpose:** Credit union employees assigned to branches — tellers, loan officers, branch managers, and member services staff.

## Columns

| Column | Type | Nullable | Description | Example |
|---|---|---|---|---|
| staff_id | INT | NOT NULL | Surrogate primary key | 201 |
| branch_id | INT | NOT NULL | FK — the branch this staff member is assigned to | 10 |
| first_name | VARCHAR(100) | NOT NULL | Staff first name | Marcus |
| last_name | VARCHAR(100) | NOT NULL | Staff last name | Trevino |
| role_cd | VARCHAR(20) | NOT NULL | TELLER, LOAN_OFFICER, BRANCH_MGR, MEMBER_SERVICES | TELLER |
| start_date | DATE | NOT NULL | Date employment began | 2022-08-15 |
| end_date | DATE | NULL | Date employment ended; NULL = currently active | NULL |

## Primary key
staff_id

## Foreign keys / relationships
- `branch_id` → `branches.branch_id`

## Naming conventions
- Current employees: WHERE end_date IS NULL.
- staff.staff_id is referenced by transactions.teller_id and loan_status_history.recorded_by.
```

- [ ] **Step 11: Create `schema_docs/ref_channel_codes.md`**

```markdown
# TABLE: ref_channel_codes

**Subject area:** Branch/channel
**Purpose:** Reference table of transaction channels (how a transaction or interaction was initiated).

## Columns

| Column | Type | Nullable | Description | Example |
|---|---|---|---|---|
| channel_cd | VARCHAR(10) | NOT NULL | Short code — primary key and FK target | BRANCH |
| channel_name | VARCHAR(100) | NOT NULL | Human-readable channel name | Branch Teller |
| is_digital | BIT | NOT NULL | 1 if the channel is digital/remote; 0 if in-person | 0 |
| description | VARCHAR(500) | NULL | Additional notes about the channel | NULL |

## Primary key
channel_cd

## Sample rows
BRANCH = Branch Teller (is_digital=0), ATM = ATM (is_digital=0), ONLINE = Online Banking (is_digital=1), MOBILE = Mobile App (is_digital=1), CARD_PRESENT = Card POS (is_digital=0), CARD_NOT_PRESENT = Card CNP/online (is_digital=1)

## Foreign keys / relationships
*(none — reference/lookup table)*
```

- [ ] **Step 12: Create `schema_docs/ref_status_codes.md`**

```markdown
# TABLE: ref_status_codes

**Subject area:** Branch/channel
**Purpose:** Shared reference table for status codes used across multiple entities (members, accounts, loans, cards). The composite primary key (status_cd + entity_type) allows the same code value (e.g., 'ACTIVE') to exist for different entity types.

## Columns

| Column | Type | Nullable | Description | Example |
|---|---|---|---|---|
| status_cd | VARCHAR(10) | NOT NULL | Status code — part of composite PK | ACTIVE |
| entity_type | VARCHAR(20) | NOT NULL | The entity this code applies to: MEMBER, ACCOUNT, LOAN, CARD — part of composite PK | MEMBER |
| status_name | VARCHAR(100) | NOT NULL | Human-readable status name | Active Member |
| is_active | BIT | NOT NULL | 1 if this status indicates an open/active record | 1 |
| description | VARCHAR(500) | NULL | Longer description of what this status means | NULL |

## Primary key
(status_cd, entity_type) — composite

## Foreign keys / relationships
*(none — reference/lookup table)*

## Naming conventions
- Always filter by entity_type when joining: e.g., WHERE entity_type = 'LOAN'.
- is_active = 1 covers: ACTIVE (member), ACTIVE (account), CURRENT/DLQ_* (loan), ACTIVE (card).
```

- [ ] **Step 13: Verify all 20 schema docs exist**

```powershell
(Get-ChildItem schema_docs/ -Filter *.md).Count
```

Expected: `20`

- [ ] **Step 14: Commit**

```powershell
git add schema_docs/
git commit -m "feat: add lending, cards, and branch/channel schema docs (12 tables, 20 total)"
```

---

## Task 4: Ingestion pipeline

**Files:**
- Create: `poc-sql-assistant/ingest/build_index.py`
- Create: `poc-sql-assistant/tests/test_build_index.py`

**Prerequisite for the integration test:** Ollama must be running (`ollama serve`) and `nomic-embed-text` must be pulled (`ollama pull nomic-embed-text`). Set `$env:OLLAMA_RUNNING = "1"` before running.

- [ ] **Step 1: Write the failing integration test**

`tests/test_build_index.py`:
```python
import os
import pytest
from pathlib import Path
from ingest.build_index import build_index

SCHEMA_DOCS = Path(__file__).parent.parent / "schema_docs"

@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("OLLAMA_RUNNING") != "1",
    reason="Requires Ollama running. Set OLLAMA_RUNNING=1 to enable.",
)
def test_build_index_returns_positive_chunk_count(tmp_path):
    chroma_path = tmp_path / "chroma_db"
    count = build_index(schema_docs_path=SCHEMA_DOCS, chroma_path=chroma_path)
    assert count > 0, "Expected at least one chunk to be indexed"
    assert chroma_path.exists(), "Chroma DB directory should be created"


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("OLLAMA_RUNNING") != "1",
    reason="Requires Ollama running. Set OLLAMA_RUNNING=1 to enable.",
)
def test_build_index_wipes_and_rebuilds(tmp_path):
    chroma_path = tmp_path / "chroma_db"
    count_first = build_index(schema_docs_path=SCHEMA_DOCS, chroma_path=chroma_path)
    count_second = build_index(schema_docs_path=SCHEMA_DOCS, chroma_path=chroma_path)
    assert count_first == count_second, "Rebuilding should produce the same chunk count"
```

- [ ] **Step 2: Run the test — confirm it is skipped (not failed) without OLLAMA_RUNNING**

```powershell
pytest tests/test_build_index.py -v
```

Expected: both tests show `SKIPPED`.

- [ ] **Step 3: Implement `ingest/build_index.py`**

```python
import shutil
from pathlib import Path

import chromadb
from llama_index.core import SimpleDirectoryReader, StorageContext, VectorStoreIndex, Settings
from llama_index.embeddings.ollama import OllamaEmbedding
from llama_index.vector_stores.chroma import ChromaVectorStore

SCHEMA_DOCS = Path(__file__).parent.parent / "schema_docs"
CHROMA_PATH = Path(__file__).parent.parent / "chroma_db"
COLLECTION = "schema_docs"
CHUNK_SIZE = 1024
CHUNK_OVERLAP = 128


def build_index(
    schema_docs_path: Path = SCHEMA_DOCS,
    chroma_path: Path = CHROMA_PATH,
) -> int:
    """Wipe and rebuild the Chroma index from schema_docs_path. Returns chunk count."""
    if chroma_path.exists():
        shutil.rmtree(chroma_path)

    Settings.embed_model = OllamaEmbedding(model_name="nomic-embed-text")
    Settings.chunk_size = CHUNK_SIZE
    Settings.chunk_overlap = CHUNK_OVERLAP

    docs = SimpleDirectoryReader(
        str(schema_docs_path),
        recursive=False,
        required_exts=[".md"],
    ).load_data()

    client = chromadb.PersistentClient(path=str(chroma_path))
    collection = client.get_or_create_collection(COLLECTION)
    vector_store = ChromaVectorStore(chroma_collection=collection)
    storage_context = StorageContext.from_defaults(vector_store=vector_store)

    VectorStoreIndex.from_documents(docs, storage_context=storage_context)

    chunk_count = collection.count()
    if chunk_count == 0:
        raise RuntimeError(
            f"Index built but contains 0 chunks. Check that {schema_docs_path} contains .md files "
            "and that Ollama is running with nomic-embed-text pulled."
        )
    return chunk_count


if __name__ == "__main__":
    count = build_index()
    print(f"Index built: {count} chunks from {SCHEMA_DOCS}")
```

- [ ] **Step 4: Run integration tests with Ollama running**

```powershell
$env:OLLAMA_RUNNING = "1"
pytest tests/test_build_index.py -v
```

Expected: both tests `PASSED`.

- [ ] **Step 5: Commit**

```powershell
git add ingest/build_index.py tests/test_build_index.py
git commit -m "feat: add ingestion pipeline (build_index) with integration tests"
```

---

## Task 5: Grounding checker

**Files:**
- Create: `poc-sql-assistant/eval/checker.py`
- Create: `poc-sql-assistant/tests/test_checker.py`

These are pure unit tests — no Ollama, no Chroma, no external dependencies.

- [ ] **Step 1: Write the failing tests**

`tests/test_checker.py`:
```python
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


# --- _load_schema_names ---

def test_load_schema_names_returns_table_from_filename(minimal_schema_docs):
    tables, columns = _load_schema_names(minimal_schema_docs)
    assert "members" in tables
    assert "loans" in tables

def test_load_schema_names_returns_columns(minimal_schema_docs):
    tables, columns = _load_schema_names(minimal_schema_docs)
    assert "member_id" in columns
    assert "first_name" in columns


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
```

- [ ] **Step 2: Run — verify all tests fail**

```powershell
pytest tests/test_checker.py -v
```

Expected: all tests `FAILED` with `ModuleNotFoundError` or similar.

- [ ] **Step 3: Implement `eval/checker.py`**

```python
import re
from pathlib import Path

SCHEMA_DOCS = Path(__file__).parent.parent / "schema_docs"

# Single-character and very short identifiers that appear in SQL but are not table/column names.
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
    # Strip string literals to avoid false positives inside quoted values.
    sql_clean = re.sub(r"'[^']*'", " ", sql_lower)

    tables: set[str] = set()
    columns: set[str] = set()

    # FROM / JOIN <table> [alias]
    for match in re.finditer(
        r"(?:from|join)\s+(\w+)(?:\s+(?:as\s+)?\w+)?", sql_clean
    ):
        name = match.group(1)
        if name not in _SQL_NOISE and len(name) > 2:
            tables.add(name)

    # table.column patterns
    for match in re.finditer(r"(\w+)\.(\w+)", sql_clean):
        left, right = match.group(1), match.group(2)
        if left not in _SQL_NOISE and len(left) > 1:
            tables.add(left)   # may be an alias, but captured anyway
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
    explanation = (result.get("explanation") or "").lower()

    # --- Trick question path ---
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

    # --- Standard question path ---
    if not sql:
        return {"score": 0.0, "reason": "No SQL generated"}

    ref_tables, ref_columns = _extract_sql_identifiers(sql)

    # Hallucination check: any referenced table that is not in the schema and
    # is not a plausible short alias (single char or two chars).
    hallucinated = {
        t for t in ref_tables
        if t not in schema_tables and len(t) > 2
    }
    if hallucinated:
        return {
            "score": 0.0,
            "reason": f"Hallucinated table names: {', '.join(sorted(hallucinated))}",
        }

    # Coverage check
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
```

- [ ] **Step 4: Run tests — verify all pass**

```powershell
pytest tests/test_checker.py -v
```

Expected: all 11 tests `PASSED`.

- [ ] **Step 5: Commit**

```powershell
git add eval/checker.py tests/test_checker.py
git commit -m "feat: add grounding checker with unit tests"
```

---

## Task 6: Assistant core

**Files:**
- Create: `poc-sql-assistant/assistant/sql_assistant.py`
- Create: `poc-sql-assistant/tests/test_sql_assistant.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_sql_assistant.py`:
```python
import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from assistant.sql_assistant import answer_question, log_result, _extract_sql


# --- _extract_sql ---

def test_extract_sql_from_code_fence():
    content = "Here is the query:\n```sql\nSELECT * FROM members\n```\nExplanation follows."
    assert _extract_sql(content) == "SELECT * FROM members"

def test_extract_sql_from_generic_fence():
    content = "```\nSELECT loan_id FROM loans\n```"
    assert _extract_sql(content) == "SELECT loan_id FROM loans"

def test_extract_sql_no_fence_returns_empty():
    content = "I cannot answer this from the provided schema."
    assert _extract_sql(content) == ""


# --- answer_question ---

def _make_mock_openai(embed_vector, completion_text):
    mock = MagicMock()
    embed_resp = MagicMock()
    embed_resp.data = [MagicMock(embedding=embed_vector)]
    mock.embeddings.create.return_value = embed_resp
    completion = MagicMock()
    completion.choices = [MagicMock(message=MagicMock(content=completion_text))]
    mock.chat.completions.create.return_value = completion
    return mock


def _make_mock_chroma(chunks, filenames):
    collection = MagicMock()
    collection.query.return_value = {
        "documents": [chunks],
        "metadatas": [[{"file_name": f} for f in filenames]],
    }
    collection.count.return_value = len(chunks)
    client = MagicMock()
    client.get_collection.return_value = collection
    return client


def test_answer_question_rag_on_returns_citations(tmp_path):
    mock_ollama = _make_mock_openai(
        embed_vector=[0.1] * 768,
        completion_text="```sql\nSELECT m.member_id, l.loan_id FROM members m JOIN loans l ON m.member_id = l.member_id\n```\nJoins members to loans.",
    )
    mock_chroma_client = _make_mock_chroma(
        chunks=["members table content...", "loans table content..."],
        filenames=["members.md", "loans.md"],
    )

    with patch("assistant.sql_assistant.ollama", mock_ollama), \
         patch("assistant.sql_assistant.chromadb.PersistentClient", return_value=mock_chroma_client):
        result = answer_question("Show members with their loan IDs", rag_enabled=True, chroma_path=tmp_path)

    assert result["rag_enabled"] is True
    assert "members.md" in result["citations"]
    assert "loans.md" in result["citations"]
    assert "members" in result["sql"].lower()
    assert result["chunk_count"] == 2
    assert result["eval_score"] is None  # not set by answer_question itself


def test_answer_question_rag_off_has_no_citations(tmp_path):
    mock_ollama = _make_mock_openai(
        embed_vector=[0.1] * 768,
        completion_text="```sql\nSELECT * FROM some_table\n```",
    )
    with patch("assistant.sql_assistant.ollama", mock_ollama):
        result = answer_question("Show all members", rag_enabled=False, chroma_path=tmp_path)

    assert result["rag_enabled"] is False
    assert result["citations"] == []
    assert result["chunk_count"] == 0
    assert result["raw_chunks"] == []


def test_answer_question_chroma_missing_raises_on_rag(tmp_path):
    mock_ollama = _make_mock_openai([0.1] * 768, "")
    missing_path = tmp_path / "nonexistent_chroma"

    mock_client = MagicMock()
    mock_client.get_collection.side_effect = Exception("Collection not found")

    with patch("assistant.sql_assistant.ollama", mock_ollama), \
         patch("assistant.sql_assistant.chromadb.PersistentClient", return_value=mock_client):
        with pytest.raises(RuntimeError, match="build_index"):
            answer_question("any question", rag_enabled=True, chroma_path=missing_path)


def test_log_result_appends_jsonl(tmp_path):
    result = {
        "timestamp": "2026-06-07T14:00:00Z",
        "question": "test",
        "rag_enabled": True,
        "sql": "SELECT 1",
        "explanation": "test",
        "citations": ["members.md"],
        "raw_chunks": ["chunk text here"],  # should be omitted from log
        "chunk_count": 1,
        "latency_ms": 100,
        "model": "qwen2.5-coder:7b",
        "eval_score": None,
        "eval_reason": None,
    }
    log_path = tmp_path / "queries.jsonl"
    log_result(result, logs_path=log_path)

    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["question"] == "test"
    assert "raw_chunks" not in record, "raw_chunks must not be written to the log"

    # Second call appends
    log_result(result, logs_path=log_path)
    assert len(log_path.read_text(encoding="utf-8").strip().splitlines()) == 2
```

- [ ] **Step 2: Run — verify all tests fail**

```powershell
pytest tests/test_sql_assistant.py -v
```

Expected: all tests `FAILED` with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `assistant/sql_assistant.py`**

```python
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import chromadb
from openai import OpenAI

CHROMA_PATH = Path(__file__).parent.parent / "chroma_db"
LOGS_PATH = Path(__file__).parent.parent / "logs" / "queries.jsonl"
COLLECTION = "schema_docs"
DEFAULT_MODEL = "qwen2.5-coder:7b"
DEFAULT_K = 5

SYSTEM_PROMPT = (
    "You are a SQL-drafting assistant for a credit union's internal data warehouse.\n"
    "When schema context is provided, you MUST only reference tables and columns that "
    "appear in that context — never invent table or column names.\n"
    "If the schema context does not contain what is needed to answer the question, "
    "say so explicitly rather than guessing.\n"
    "Always provide:\n"
    "1. The SQL query in a ```sql code block\n"
    "2. A brief explanation of the join logic and any assumptions you made."
)

ollama = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")


def _embed(text: str) -> list[float]:
    resp = ollama.embeddings.create(model="nomic-embed-text", input=text)
    return resp.data[0].embedding


def _retrieve(
    question: str, k: int, chroma_path: Path
) -> tuple[list[str], list[str]]:
    """Return (chunk_texts, deduplicated_citation_filenames)."""
    try:
        client = chromadb.PersistentClient(path=str(chroma_path))
        collection = client.get_collection(COLLECTION)
    except Exception as exc:
        raise RuntimeError(
            f"Chroma collection '{COLLECTION}' not found at {chroma_path}. "
            "Run `python ingest/build_index.py` first."
        ) from exc

    actual_k = min(k, collection.count())
    if actual_k == 0:
        raise RuntimeError(
            f"Chroma index at {chroma_path} is empty. "
            "Run `python ingest/build_index.py` first."
        )

    embedding = _embed(question)
    results = collection.query(
        query_embeddings=[embedding],
        n_results=actual_k,
        include=["documents", "metadatas"],
    )
    chunks: list[str] = results["documents"][0]
    filenames: list[str] = [
        meta.get("file_name", "unknown") for meta in results["metadatas"][0]
    ]
    # Deduplicate citations while preserving order.
    seen: set[str] = set()
    citations: list[str] = []
    for f in filenames:
        if f not in seen:
            seen.add(f)
            citations.append(f)
    return chunks, citations


def _extract_sql(content: str) -> str:
    """Extract the first SQL block from the model response."""
    # Match ```sql ... ``` or ``` ... ```
    match = re.search(r"```(?:sql)?\s*\n?(.*?)```", content, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return ""


def answer_question(
    question: str,
    rag_enabled: bool = True,
    model: str = DEFAULT_MODEL,
    k: int = DEFAULT_K,
    chroma_path: Path = CHROMA_PATH,
) -> dict:
    """
    Core assistant function. Returns a result dict with sql, explanation,
    citations, and metadata. Caller is responsible for logging via log_result().
    """
    start = time.monotonic()
    chunks: list[str] = []
    citations: list[str] = []

    if rag_enabled:
        chunks, citations = _retrieve(question, k, chroma_path)

    context_block = ""
    if chunks:
        parts = []
        for i, chunk in enumerate(chunks):
            label = citations[i] if i < len(citations) else "unknown"
            parts.append(f"[Source: {label}]\n{chunk}")
        context_block = "\n\n## Schema Context\n\n" + "\n\n---\n\n".join(parts)

    user_content = f"{context_block}\n\n## Question\n{question}".strip()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    resp = ollama.chat.completions.create(model=model, messages=messages)
    content = resp.choices[0].message.content

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "question": question,
        "rag_enabled": rag_enabled,
        "sql": _extract_sql(content),
        "explanation": content,
        "citations": citations,
        "raw_chunks": chunks,
        "chunk_count": len(chunks),
        "latency_ms": int((time.monotonic() - start) * 1000),
        "model": model,
        "eval_score": None,
        "eval_reason": None,
    }


def log_result(result: dict, logs_path: Path = LOGS_PATH) -> None:
    """Append one JSON record to the query log. raw_chunks omitted to keep log compact."""
    logs_path.parent.mkdir(parents=True, exist_ok=True)
    record = {k: v for k, v in result.items() if k != "raw_chunks"}
    with logs_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def _cli_loop(chroma_path: Path = CHROMA_PATH, model: str = DEFAULT_MODEL) -> None:
    print(f"SQL Assistant (model={model}, RAG={'on' if chroma_path.exists() else 'OFF — run build_index.py'})")
    print("Type your question. Enter blank line to quit.\n")
    while True:
        try:
            question = input(">>> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break
        if not question:
            break
        result = answer_question(question, rag_enabled=True, model=model, chroma_path=chroma_path)
        log_result(result)
        print(f"\n{result['explanation']}")
        if result["citations"]:
            print(f"\nSources: {', '.join(result['citations'])}")
        print(f"({result['latency_ms']}ms)\n")


if __name__ == "__main__":
    _cli_loop()
```

- [ ] **Step 4: Run tests — verify all pass**

```powershell
pytest tests/test_sql_assistant.py -v
```

Expected: all 7 tests `PASSED`.

- [ ] **Step 5: Commit**

```powershell
git add assistant/sql_assistant.py tests/test_sql_assistant.py
git commit -m "feat: add assistant core (answer_question, log_result, CLI) with unit tests"
```

---

## Task 7: Test questions + eval runner

**Files:**
- Create: `poc-sql-assistant/eval/test_questions.yaml`
- Create: `poc-sql-assistant/eval/run_eval.py`

No unit tests for run_eval — it's an integration orchestrator. Validated in Task 10.

- [ ] **Step 1: Create `eval/test_questions.yaml`**

```yaml
# 15 curated questions across single-table, cross-subject, and trick categories.
# expected_tables: [] marks trick questions (schema doesn't contain what's asked).

- question: "What columns does the members table contain?"
  expected_tables: [members]
  expected_columns: [member_id, first_name, last_name]
  notes: "Single-table lookup. Establishes RAG baseline — model must name real columns."

- question: "Write a query to list all members who joined the credit union in 2023."
  expected_tables: [members]
  expected_columns: [member_id, member_since_date]
  notes: "Single-table with date filter. Tests correct column name retrieval."

- question: "Which table tracks each member's current mailing address, and what column links it back to the member?"
  expected_tables: [addresses]
  expected_columns: [member_id, address_type_cd, end_date]
  notes: "Single-table lookup — must find addresses and identify member_id as the FK."

- question: "Write a query returning each active member's name and all open deposit accounts they hold."
  expected_tables: [members, accounts]
  expected_columns: [member_id, first_name, last_name, account_id, status_cd]
  notes: "Cross-subject join: member/party → deposits. Tests that retrieval bridges both docs."

- question: "Show the current ledger balance and available balance for all checking accounts."
  expected_tables: [accounts, account_types]
  expected_columns: [account_id, current_balance, available_balance, account_type_cd]
  notes: "Deposit area join: accounts → account_types. Tests reference table retrieval."

- question: "Write a query showing each member's active loans and their current delinquency status (days past due)."
  expected_tables: [members, loans, loan_status_history]
  expected_columns: [member_id, loan_id, days_past_due, status_cd]
  notes: "Three-table cross-subject join. Primary difficulty test — must find loan_status_history."

- question: "Find all loans that are 30 or more days past due as of today."
  expected_tables: [loans, loan_status_history]
  expected_columns: [loan_id, days_past_due, end_date]
  notes: "Delinquency query. Tests awareness that days_past_due lives in loan_status_history, not loans."

- question: "Which table contains the amortization schedule showing how each loan payment is split between principal and interest?"
  expected_tables: [payment_schedules]
  expected_columns: [loan_id, principal_portion, interest_portion, is_paid]
  notes: "Lending lookup — must identify payment_schedules and its columns."

- question: "Write a query to find all members who have a card account and show their current reward points balance."
  expected_tables: [members, card_accounts, card_rewards]
  expected_columns: [member_id, card_account_id, points_balance]
  notes: "Three-table cross-subject: member → card → rewards. Tests multi-hop retrieval."

- question: "How would I join card transactions to the channel reference table to get the channel name for each purchase?"
  expected_tables: [card_transactions, ref_channel_codes]
  expected_columns: [card_txn_id, channel_cd, channel_name]
  notes: "Cards → reference. Tests retrieval of ref_ table when asked about channel."

- question: "Write a query listing every teller transaction from the Downtown Springfield Branch in the last 30 days."
  expected_tables: [transactions, staff, branches]
  expected_columns: [transaction_id, teller_id, branch_id, branch_name]
  notes: "Cross-subject: deposits → branch/channel. Multi-hop via staff.branch_id."

- question: "Which table would I use to find a member's mobile phone number, and how is consent tracked?"
  expected_tables: [contact_info]
  expected_columns: [member_id, contact_type_cd, contact_value, is_consent_given]
  notes: "Member/party lookup. Tests retrieval of contact_info and consent column."

# Trick questions — model should explicitly decline, not hallucinate.

- question: "Write a query to pull a member's investment portfolio holdings and current market value."
  expected_tables: []
  expected_columns: []
  notes: "TRICK: No investment/portfolio tables exist in this schema. Must decline."

- question: "Which table stores mortgage escrow payments and impound account balances?"
  expected_tables: []
  expected_columns: []
  notes: "TRICK: No escrow/impound tables exist. Must decline."

- question: "Show me the query for pulling a member's credit score history from our bureau pull table."
  expected_tables: []
  expected_columns: []
  notes: "TRICK: No credit bureau pull table exists in this schema. Must decline."
```

- [ ] **Step 2: Implement `eval/run_eval.py`**

```python
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from assistant.sql_assistant import answer_question, log_result, CHROMA_PATH, LOGS_PATH, DEFAULT_MODEL
from eval.checker import check_answer, SCHEMA_DOCS

TEST_QUESTIONS = Path(__file__).parent / "test_questions.yaml"
DEFAULT_REPORT = ROOT / "logs" / "eval_report.md"


def run_eval(
    report_path: Path = DEFAULT_REPORT,
    model: str = DEFAULT_MODEL,
    chroma_path: Path = CHROMA_PATH,
    logs_path: Path = LOGS_PATH,
    schema_docs: Path = SCHEMA_DOCS,
) -> dict:
    questions = yaml.safe_load(TEST_QUESTIONS.read_text(encoding="utf-8"))
    rows: list[dict] = []

    for i, q in enumerate(questions, 1):
        question = q["question"]
        expected_tables = q.get("expected_tables", [])
        expected_columns = q.get("expected_columns", [])
        print(f"[{i}/{len(questions)}] {question[:70]}...")

        rag_result = answer_question(question, rag_enabled=True, model=model, chroma_path=chroma_path)
        rag_check = check_answer(rag_result, expected_tables, expected_columns, schema_docs)
        rag_result["eval_score"] = rag_check["score"]
        rag_result["eval_reason"] = rag_check["reason"]
        log_result(rag_result, logs_path)

        no_rag_result = answer_question(question, rag_enabled=False, model=model, chroma_path=chroma_path)
        no_rag_check = check_answer(no_rag_result, expected_tables, expected_columns, schema_docs)
        no_rag_result["eval_score"] = no_rag_check["score"]
        no_rag_result["eval_reason"] = no_rag_check["reason"]
        log_result(no_rag_result, logs_path)

        rows.append({
            "question": question,
            "rag": rag_check,
            "no_rag": no_rag_check,
            "citations": rag_result["citations"],
            "rag_latency_ms": rag_result["latency_ms"],
        })
        print(f"  RAG={rag_check['score']:.1f}  no-RAG={no_rag_check['score']:.1f}  {rag_check['reason']}")

    rag_scores = [r["rag"]["score"] for r in rows]
    no_rag_scores = [r["no_rag"]["score"] for r in rows]
    report_md = _build_report(rows, rag_scores, no_rag_scores, model)

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report_md, encoding="utf-8")
    print(f"\nReport written → {report_path}")
    print(f"RAG mean score:    {sum(rag_scores)/len(rag_scores):.2f}")
    print(f"No-RAG mean score: {sum(no_rag_scores)/len(no_rag_scores):.2f}")

    return {
        "rag_mean": sum(rag_scores) / len(rag_scores),
        "no_rag_mean": sum(no_rag_scores) / len(no_rag_scores),
        "rows": rows,
    }


def _build_report(rows: list[dict], rag_scores: list, no_rag_scores: list, model: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# SQL Assistant Eval Report",
        f"Generated: {ts} | Model: {model}",
        "",
        "## Summary",
        "",
        "| | Mean Score |",
        "|---|---|",
        f"| RAG enabled | **{sum(rag_scores)/len(rag_scores):.2f}** |",
        f"| No RAG (baseline) | {sum(no_rag_scores)/len(no_rag_scores):.2f} |",
        "",
        "## Question-by-question results",
        "",
        "| # | Question | RAG | No-RAG | Δ | Citations | Reason |",
        "|---|---|---|---|---|---|---|",
    ]
    for i, row in enumerate(rows, 1):
        delta = row["rag"]["score"] - row["no_rag"]["score"]
        delta_str = f"+{delta:.1f}" if delta > 0 else f"{delta:.1f}"
        q_short = row["question"][:55] + ("…" if len(row["question"]) > 55 else "")
        cites = ", ".join(row["citations"]) or "—"
        lines.append(
            f"| {i} | {q_short} | {row['rag']['score']:.1f} | {row['no_rag']['score']:.1f} "
            f"| {delta_str} | {cites} | {row['rag']['reason']} |"
        )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    run_eval()
```

- [ ] **Step 3: Verify YAML is valid**

```powershell
python -c "import yaml; qs = yaml.safe_load(open('eval/test_questions.yaml')); print(f'{len(qs)} questions loaded')"
```

Expected: `15 questions loaded`

- [ ] **Step 4: Commit**

```powershell
git add eval/test_questions.yaml eval/run_eval.py
git commit -m "feat: add 15 curated test questions and eval runner with RAG-on/off comparison"
```

---

## Task 8: Refresh scheduler

**Files:**
- Create: `poc-sql-assistant/refresh/refresh_scheduler.py`
- Create: `poc-sql-assistant/tests/test_refresh.py`

Pure unit tests — no Ollama, no Chroma. `run_refresh_cycle` is tested with mock files using `tmp_path`.

- [ ] **Step 1: Write the failing tests**

`tests/test_refresh.py`:
```python
import json
import time
from pathlib import Path
import pytest
from refresh.refresh_scheduler import _hash_docs, _load_state, _save_state, run_refresh_cycle


def test_hash_docs_is_deterministic(minimal_schema_docs):
    h1 = _hash_docs(minimal_schema_docs)
    h2 = _hash_docs(minimal_schema_docs)
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex digest


def test_hash_docs_changes_when_file_changes(minimal_schema_docs):
    h_before = _hash_docs(minimal_schema_docs)
    (minimal_schema_docs / "members.md").write_text("changed content", encoding="utf-8")
    h_after = _hash_docs(minimal_schema_docs)
    assert h_before != h_after


def test_hash_docs_changes_when_file_added(minimal_schema_docs):
    h_before = _hash_docs(minimal_schema_docs)
    (minimal_schema_docs / "new_table.md").write_text("# TABLE: new_table\n", encoding="utf-8")
    h_after = _hash_docs(minimal_schema_docs)
    assert h_before != h_after


def test_load_state_returns_empty_string_when_no_file(tmp_path):
    state_file = tmp_path / "refresh_state.json"
    assert _load_state(state_file) == ""


def test_save_and_load_state_roundtrip(tmp_path):
    state_file = tmp_path / "refresh_state.json"
    _save_state(state_file, "abc123")
    assert _load_state(state_file) == "abc123"


def test_run_refresh_cycle_skipped_when_no_change(minimal_schema_docs, tmp_path, mocker):
    chroma_path = tmp_path / "chroma_db"
    state_file = tmp_path / "refresh_state.json"
    refresh_log = tmp_path / "refresh_log.jsonl"

    # Pre-populate state with the current hash so no change is detected.
    current_hash = _hash_docs(minimal_schema_docs)
    _save_state(state_file, current_hash)

    mock_build = mocker.patch("refresh.refresh_scheduler.build_index")
    action = run_refresh_cycle(minimal_schema_docs, chroma_path, state_file, refresh_log)

    assert action == "skipped"
    mock_build.assert_not_called()
    log_records = [json.loads(l) for l in refresh_log.read_text().splitlines()]
    assert log_records[0]["action"] == "skipped"


def test_run_refresh_cycle_reindexed_when_changed(minimal_schema_docs, tmp_path, mocker):
    chroma_path = tmp_path / "chroma_db"
    state_file = tmp_path / "refresh_state.json"
    refresh_log = tmp_path / "refresh_log.jsonl"

    # State is empty — docs have changed from "nothing".
    mock_build = mocker.patch("refresh.refresh_scheduler.build_index", return_value=10)
    action = run_refresh_cycle(minimal_schema_docs, chroma_path, state_file, refresh_log)

    assert action == "reindexed"
    mock_build.assert_called_once()
    log_records = [json.loads(l) for l in refresh_log.read_text().splitlines()]
    assert log_records[0]["action"] == "reindexed"

    # Running again immediately — state now matches, should skip.
    action2 = run_refresh_cycle(minimal_schema_docs, chroma_path, state_file, refresh_log)
    assert action2 == "skipped"
```

- [ ] **Step 2: Run — verify all tests fail**

```powershell
pytest tests/test_refresh.py -v
```

Expected: `FAILED` with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `refresh/refresh_scheduler.py`**

```python
import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from ingest.build_index import build_index, SCHEMA_DOCS, CHROMA_PATH

STATE_FILE = Path(__file__).parent.parent / "logs" / "refresh_state.json"
REFRESH_LOG = Path(__file__).parent.parent / "logs" / "refresh_log.jsonl"


def _hash_docs(schema_docs: Path) -> str:
    """SHA-256 over sorted filenames + file contents."""
    h = hashlib.sha256()
    for f in sorted(schema_docs.glob("*.md")):
        h.update(f.name.encode("utf-8"))
        h.update(f.read_bytes())
    return h.hexdigest()


def _load_state(state_file: Path) -> str:
    """Return the last-known hash, or empty string if no state file."""
    if not state_file.exists():
        return ""
    return json.loads(state_file.read_text(encoding="utf-8")).get("hash", "")


def _save_state(state_file: Path, hash_val: str) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(
        json.dumps({"hash": hash_val, "updated": datetime.now(timezone.utc).isoformat()}),
        encoding="utf-8",
    )


def _log_refresh(
    refresh_log: Path,
    action: str,
    tables_found: int,
    duration_ms: int,
) -> None:
    refresh_log.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "tables_found": tables_found,
        "duration_ms": duration_ms,
    }
    with refresh_log.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def run_refresh_cycle(
    schema_docs: Path = SCHEMA_DOCS,
    chroma_path: Path = CHROMA_PATH,
    state_file: Path = STATE_FILE,
    refresh_log: Path = REFRESH_LOG,
) -> str:
    """
    Check whether schema docs have changed since the last cycle.
    If changed: rebuild the Chroma index and update stored hash.
    Returns 'reindexed' or 'skipped'.
    """
    t0 = time.monotonic()
    current_hash = _hash_docs(schema_docs)
    last_hash = _load_state(state_file)
    tables_found = len(list(schema_docs.glob("*.md")))

    if current_hash == last_hash:
        duration_ms = int((time.monotonic() - t0) * 1000)
        _log_refresh(refresh_log, "skipped", tables_found, duration_ms)
        return "skipped"

    build_index(schema_docs_path=schema_docs, chroma_path=chroma_path)
    _save_state(state_file, current_hash)
    duration_ms = int((time.monotonic() - t0) * 1000)
    _log_refresh(refresh_log, "reindexed", tables_found, duration_ms)
    return "reindexed"


def run_scheduler(
    interval_seconds: int = 120,
    schema_docs: Path = SCHEMA_DOCS,
    chroma_path: Path = CHROMA_PATH,
) -> None:
    """Loop forever, running a refresh cycle every interval_seconds. Ctrl-C to stop."""
    print(f"Refresh scheduler started — interval={interval_seconds}s. Ctrl-C to stop.")
    while True:
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
        action = run_refresh_cycle(schema_docs, chroma_path)
        print(f"[{ts}] {action}")
        time.sleep(interval_seconds)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Schema doc refresh scheduler")
    parser.add_argument(
        "--interval", type=int, default=120,
        help="Seconds between refresh cycles (demo mode). Default: 120.",
    )
    parser.add_argument(
        "--once", action="store_true",
        help="Run exactly one refresh cycle and exit (for Windows Task Scheduler).",
    )
    args = parser.parse_args()

    if args.once:
        action = run_refresh_cycle()
        print(f"Refresh cycle complete: {action}")
    else:
        run_scheduler(interval_seconds=args.interval)
```

- [ ] **Step 4: Run tests — verify all pass**

```powershell
pytest tests/test_refresh.py -v
```

Expected: all 7 tests `PASSED`.

- [ ] **Step 5: Commit**

```powershell
git add refresh/refresh_scheduler.py tests/test_refresh.py
git commit -m "feat: add refresh scheduler with hash-change detection and unit tests"
```

---

## Task 9: SQL Server extraction script

**Files:**
- Create: `poc-sql-assistant/extraction/extract_schema_from_sqlserver.py`

No automated test — requires a real SQL Server connection. Validated manually when a connection string is available.

- [ ] **Step 1: Implement `extraction/extract_schema_from_sqlserver.py`**

```python
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
```

- [ ] **Step 2: Smoke-test the script's argument validation (no DB connection needed)**

```powershell
python extraction/extract_schema_from_sqlserver.py
```

Expected: exits with the `Set SQL_SERVER_DSN before running.` message and usage example.

- [ ] **Step 3: Commit**

```powershell
git add extraction/extract_schema_from_sqlserver.py
git commit -m "feat: add SQL Server schema extraction script (read-only, pyodbc)"
```

---

## Task 10: End-to-end validation, Windows Task Scheduler, and Open WebUI

**Prerequisites:** Ollama running, `qwen2.5-coder:7b` and `nomic-embed-text` pulled.

- [ ] **Step 1: Run the full unit test suite — confirm no regressions**

```powershell
pytest -v --ignore=tests/test_build_index.py
```

Expected: all non-integration tests `PASSED`.

- [ ] **Step 2: Build the index from mock schema docs**

```powershell
python ingest/build_index.py
```

Expected output: `Index built: <N> chunks from ...schema_docs` (N should be 20–80 depending on chunking).

- [ ] **Step 3: Smoke-test the CLI assistant**

```powershell
python assistant/sql_assistant.py
```

At the `>>>` prompt, type:
```
Show me the current delinquency status for all loans
```

Expected: a SQL response referencing `loans` and `loan_status_history`, with source citations listed (`loans.md`, `loan_status_history.md`). Verify `logs/queries.jsonl` now contains one record.

- [ ] **Step 4: Run the full eval — RAG-on vs. RAG-off**

```powershell
python eval/run_eval.py
```

Expected:
- Progress lines printed for all 15 questions.
- `logs/eval_report.md` created.
- RAG mean score should be noticeably higher than no-RAG mean score.
- Verify `logs/queries.jsonl` now has 30 additional records (2 per question × 15 questions), each with `eval_score` populated.

- [ ] **Step 5: Review the eval report**

```powershell
Get-Content logs/eval_report.md
```

The markdown table should show RAG-on scores ≥ no-RAG scores for most questions, with ≥ 2 trick questions scoring 1.0 for RAG-on (correctly declined). This is your "visibly better than no-RAG" artifact.

- [ ] **Step 6: Demo the refresh scheduler (2-minute demo mode)**

In a second PowerShell window, run:
```powershell
python refresh/refresh_scheduler.py --interval 120
```

Expected: first tick prints `[HH:MM:SS UTC] reindexed` (state file didn't exist). Subsequent ticks print `skipped`.

Now edit one schema doc to simulate a schema change:
```powershell
Add-Content schema_docs/members.md "`n## Notes`nAdded Q2 2026: new column `preferred_name` VARCHAR(100) NULL."
```

Within the next 120-second tick, the scheduler should print `reindexed`. Ask the assistant about `preferred_name` to confirm the index picked it up.

- [ ] **Step 7: Register as a Windows Task Scheduler job (nightly)**

In an Administrator PowerShell:
```powershell
$projectRoot = (Get-Location).Path   # run from poc-sql-assistant/
$pythonPath = (Get-Command python).Source

$action = New-ScheduledTaskAction `
    -Execute $pythonPath `
    -Argument "$projectRoot\refresh\refresh_scheduler.py --once" `
    -WorkingDirectory $projectRoot

$trigger = New-ScheduledTaskTrigger -Daily -At "02:00"

$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
    -StartWhenAvailable

Register-ScheduledTask `
    -Action $action `
    -Trigger $trigger `
    -TaskName "SQL-Assistant-Schema-Refresh" `
    -Description "Nightly schema doc refresh for the SQL-drafting assistant POC" `
    -Settings $settings `
    -RunLevel Highest
```

Verify it registered:
```powershell
Get-ScheduledTask -TaskName "SQL-Assistant-Schema-Refresh" | Select-Object TaskName, State
```

Expected: `TaskName=SQL-Assistant-Schema-Refresh, State=Ready`

Test a manual run (doesn't wait for 2AM):
```powershell
Start-ScheduledTask -TaskName "SQL-Assistant-Schema-Refresh"
Start-Sleep 10
Get-Content logs/refresh_log.jsonl | Select-Object -Last 1
```

Expected: a JSON record with `"action": "skipped"` or `"reindexed"`.

- [ ] **Step 8: Wire into Open WebUI**

1. Open `http://localhost:3000` (your running Open WebUI instance).
2. Go to **Admin Panel → Settings → Documents**.
   - Set **Embedding Model Engine** to `Ollama`.
   - Set **Embedding Model** to `nomic-embed-text`.
   - Save.
3. Go to **Workspace → Knowledge → + Create a Knowledge Base**.
   - Name: `Credit Union Schema Docs`
   - Upload all files from `schema_docs/` (drag-and-drop the folder contents).
4. In a new chat, type `#` and select `Credit Union Schema Docs` to scope the conversation.
5. Ask: *"Write a query joining members to their delinquent loans."*
   - Expected: grounded SQL referencing `members`, `loans`, `loan_status_history`.

This is the GUI layer on top of the already-validated scripted pipeline — same docs, same embedding model, different caller.

- [ ] **Step 9: Run integration tests to confirm the full stack**

```powershell
$env:OLLAMA_RUNNING = "1"
pytest -v
```

Expected: all tests `PASSED` (unit + integration).

- [ ] **Step 10: Final commit**

```powershell
git add .
git commit -m "feat: end-to-end SQL assistant POC complete — eval report, refresh scheduler, Task Scheduler, Open WebUI integration"
```

---

## Definition of Done Checklist

- [ ] `pytest -v` (unit only, no `OLLAMA_RUNNING`) passes with 0 failures
- [ ] `python ingest/build_index.py` builds index with >0 chunks
- [ ] `python eval/run_eval.py` produces `logs/eval_report.md` showing RAG mean > no-RAG mean
- [ ] `logs/queries.jsonl` contains 30 scored records from the eval run
- [ ] `python refresh/refresh_scheduler.py --interval 120` visibly picks up a schema doc edit within one tick
- [ ] `SQL-Assistant-Schema-Refresh` scheduled task registered and verified with a manual run
- [ ] Open WebUI `Credit Union Schema Docs` knowledge base returns grounded SQL in browser
- [ ] `extraction/extract_schema_from_sqlserver.py` exits with usage message when `SQL_SERVER_DSN` unset
