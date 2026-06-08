# TABLE: staff

**Subject area:** Branch/channel
**Purpose:** Credit union employees assigned to branches — tellers, loan officers, branch managers, and member services staff.

## Columns

| Column | Type | Nullable | Description | Example |
|---|---|---|---|---|
| staff_id | INT | NOT NULL | Surrogate primary key | 201 |
| branch_id | INT | NOT NULL | FK — the branch this staff member is assigned to | 10 |
| first_name | VARCHAR(100) | NOT NULL | Staff first name | Marcus |
| last_name | VARCHAR(100) | NOT NULL | Staff last name | Trevino |
| role_cd | VARCHAR(20) | NOT NULL | TELLER, LOAN_OFFICER, BRANCH_MGR, MEMBER_SERVICES | TELLER |
| start_date | DATE | NOT NULL | Date employment began | 2022-08-15 |
| end_date | DATE | NULL | Date employment ended; NULL = currently active | NULL |

## Primary key
staff_id

## Foreign keys / relationships

**Outbound (staff → other tables):**
- `branch_id` → `branches.branch_id`

**Referenced by (other tables → staff.staff_id):**
- `transactions.teller_id` (branch-initiated deposit transactions; NULL for digital/ATM)
- `loan_status_history.recorded_by` (who recorded a loan status change)

**Common join paths:**
- Teller activity by branch (cross-subject): `transactions` → `staff` (teller_id) → `branches`.
- Loan status changes by employee: `loan_status_history` → `staff` (recorded_by) → `branches`.

## Naming conventions
- Current employees: WHERE end_date IS NULL.
- staff.staff_id is referenced by transactions.teller_id and loan_status_history.recorded_by.
