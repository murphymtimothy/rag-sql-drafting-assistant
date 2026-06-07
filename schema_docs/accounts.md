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
