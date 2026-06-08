# TABLE: branches

**Subject area:** Branch/channel
**Purpose:** Physical branch locations operated by the credit union.

## Columns

| Column | Type | Nullable | Description | Example |
|---|---|---|---|---|
| branch_id | INT | NOT NULL | Surrogate primary key | 10 |
| branch_name | VARCHAR(200) | NOT NULL | Display name of the branch | Downtown Springfield Branch |
| address_id | INT | NOT NULL | FK — physical address of the branch | 88099 |
| phone | VARCHAR(20) | NOT NULL | Main branch phone number | 217-555-0100 |
| opened_date | DATE | NOT NULL | Date the branch opened | 2001-03-01 |
| is_active | BIT | NOT NULL | 1 if the branch is currently open | 1 |

## Primary key
branch_id

## Foreign keys / relationships

**Outbound (branches → other tables):**
- `address_id` → `addresses.address_id`

**Referenced by (other tables → branches.branch_id):**
- `staff.branch_id` (employees assigned to the branch)

**Common join paths:**
- Staff at a named branch: `branches` → `staff` (active = WHERE staff.end_date IS NULL).
- Teller transactions at a branch (cross-subject): `branches` → `staff` → `transactions` ON transactions.teller_id = staff.staff_id.
- Branch location / address: `branches` → `addresses`.
