# TABLE: ref_status_codes

**Subject area:** Branch/channel
**Purpose:** Shared reference table for status codes used across multiple entities (members, accounts, loans, cards). The composite primary key (status_cd + entity_type) allows the same code value (e.g., 'ACTIVE') to exist for different entity types.

## Columns

| Column | Type | Nullable | Description | Example |
|---|---|---|---|---|
| status_cd | VARCHAR(10) | NOT NULL | Status code — part of composite PK | ACTIVE |
| entity_type | VARCHAR(20) | NOT NULL | The entity this code applies to: MEMBER, ACCOUNT, LOAN, CARD — part of composite PK | MEMBER |
| status_name | VARCHAR(100) | NOT NULL | Human-readable status name | Active Member |
| is_active | BIT | NOT NULL | 1 if this status indicates an open/active record | 1 |
| description | VARCHAR(500) | NULL | Longer description of what this status means | NULL |

## Primary key
(status_cd, entity_type) — composite

## Foreign keys / relationships

**Outbound:** *(none — reference/lookup table)*

**Referenced by (other tables → ref_status_codes.status_cd, always with the matching entity_type):**
- `members.status_cd` (entity_type = 'MEMBER')
- `accounts.status_cd` (entity_type = 'ACCOUNT')
- `loans.status_cd` and `loan_status_history.status_cd` (entity_type = 'LOAN')
- `card_accounts.status_cd` (entity_type = 'CARD')

**Common join paths:**
- Resolve any status code to its name: join ON status_cd AND entity_type (the composite key) — e.g. `loans` → `ref_status_codes` ON loans.status_cd = ref.status_cd AND ref.entity_type = 'LOAN'. Always include the entity_type filter, or the same code value (e.g. 'ACTIVE') will collide across entities.

## Naming conventions
- Always filter by entity_type when joining: e.g., WHERE entity_type = 'LOAN'.
- is_active = 1 covers: ACTIVE (member), ACTIVE (account), CURRENT/DLQ_* (loan), ACTIVE (card).
