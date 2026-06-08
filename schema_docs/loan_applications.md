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

**Outbound (loan_applications → other tables):**
- `member_id` → `members.member_id`
- `loan_type_cd` → `loan_types.loan_type_cd`

**Referenced by (other tables → loan_applications.application_id):**
- `loans.application_id` (a funded loan originates from an approved application)

**Common join paths:**
- Application → funded loan: `loan_applications` → `loans` (application_id). Not every application becomes a loan (decision_cd may be DENIED / WITHDRAWN / PENDING).
- Applicant and requested product: `loan_applications` → `members` and → `loan_types`.
