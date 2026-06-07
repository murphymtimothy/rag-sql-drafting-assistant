# TABLE: contact_info

**Subject area:** Member/party
**Purpose:** Phone numbers and email addresses for members, including consent flags required for TCPA and email marketing compliance.

## Columns

| Column | Type | Nullable | Description | Example |
|---|---|---|---|---|
| contact_id | INT | NOT NULL | Surrogate primary key | 55201 |
| member_id | INT | NOT NULL | FK — the member this contact belongs to | 10042 |
| contact_type_cd | VARCHAR(15) | NOT NULL | PHONE_MOBILE, PHONE_HOME, PHONE_WORK, EMAIL | PHONE_MOBILE |
| contact_value | VARCHAR(255) | NOT NULL | The phone number or email address | 217-555-0183 |
| is_primary | BIT | NOT NULL | 1 if this is the member's preferred contact of this type | 1 |
| is_consent_given | BIT | NOT NULL | 1 if the member has consented to contact at this address/number | 1 |

## Primary key
contact_id

## Foreign keys / relationships
- `member_id` → `members.member_id`

## Naming conventions
- `is_` prefix indicates a boolean flag stored as BIT (0/1).
