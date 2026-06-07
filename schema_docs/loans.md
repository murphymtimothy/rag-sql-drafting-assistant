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
