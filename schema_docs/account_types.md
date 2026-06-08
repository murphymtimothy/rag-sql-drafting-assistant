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

**Outbound:** *(none — this is a reference/lookup table)*

**Referenced by (other tables → account_types.account_type_cd):**
- `accounts.account_type_cd`

**Common join paths:**
- Resolve a deposit account's product name and features: `accounts` → `account_types`.
