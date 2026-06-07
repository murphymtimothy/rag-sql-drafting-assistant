# TABLE: household_relationships

**Subject area:** Member/party
**Purpose:** Tracks relationships between members, such as joint ownership, beneficiary designations, and power-of-attorney arrangements.

## Columns

| Column | Type | Nullable | Description | Example |
|---|---|---|---|---|
| relationship_id | INT | NOT NULL | Surrogate primary key | 3301 |
| member_id_primary | INT | NOT NULL | FK — the primary member in the relationship | 10042 |
| member_id_related | INT | NOT NULL | FK — the related member (e.g., the beneficiary or joint owner) | 10043 |
| relationship_type_cd | VARCHAR(20) | NOT NULL | JOINT_OWNER, BENEFICIARY, POA, DEPENDENT | JOINT_OWNER |
| effective_date | DATE | NOT NULL | Date the relationship became effective | 2019-06-01 |

## Primary key
relationship_id

## Foreign keys / relationships
- `member_id_primary` → `members.member_id`
- `member_id_related` → `members.member_id`
