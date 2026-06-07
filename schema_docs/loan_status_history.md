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
