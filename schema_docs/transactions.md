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
