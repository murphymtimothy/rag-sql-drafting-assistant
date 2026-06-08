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

**Outbound (members → other tables):**
- `status_cd` → `ref_status_codes.status_cd` (filter entity_type = 'MEMBER')

**Referenced by (other tables → members.member_id):**
- `addresses.member_id`, `contact_info.member_id`, `accounts.member_id`, `loan_applications.member_id`, `loans.member_id`, `card_accounts.member_id`
- `household_relationships.member_id_primary` and `household_relationships.member_id_related` (member-to-member links)

**Common join paths (members is the hub of most cross-subject queries):**
- Deposits: `members` → `accounts` (→ `account_types` for the product name; → `transactions` for postings; → `holds` for available-balance detail).
- Lending / delinquency: `members` → `loans` → `loan_status_history` (current row WHERE end_date IS NULL gives status_cd and days_past_due).
- Cards / rewards: `members` → `card_accounts` → `card_rewards` (points_balance) or → `card_transactions` (spend).

## Naming conventions
- `_cd` suffix indicates a code that resolves against a reference table.
- `_date` suffix indicates a calendar date (DATE type, no time component).
