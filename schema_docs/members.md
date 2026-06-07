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
