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

**Outbound (holds → other tables):**
- `account_id` → `accounts.account_id`

**Referenced by:** *(none)*

**Common join paths:**
- Active holds reducing an account's available balance: `accounts` → `holds` (active = WHERE release_date IS NULL).

## Naming conventions
- Active holds: filter WHERE release_date IS NULL.
- Sum of active holds = accounts.current_balance - accounts.available_balance.
