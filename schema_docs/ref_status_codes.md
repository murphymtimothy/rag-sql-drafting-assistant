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
*(none — reference/lookup table)*

## Naming conventions
- Always filter by entity_type when joining: e.g., WHERE entity_type = 'LOAN'.
- is_active = 1 covers: ACTIVE (member), ACTIVE (account), CURRENT/DLQ_* (loan), ACTIVE (card).
