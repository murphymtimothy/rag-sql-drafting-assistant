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
