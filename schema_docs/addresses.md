# TABLE: addresses

**Subject area:** Member/party
**Purpose:** Mailing and physical addresses for members; supports multiple address types and historical address records via effective/end dates.

## Columns

| Column | Type | Nullable | Description | Example |
|---|---|---|---|---|
| address_id | INT | NOT NULL | Surrogate primary key | 88001 |
| member_id | INT | NOT NULL | FK — the member this address belongs to | 10042 |
| address_type_cd | VARCHAR(10) | NOT NULL | PRIMARY, MAILING, or SEASONAL | PRIMARY |
| street1 | VARCHAR(200) | NOT NULL | First line of street address | 742 Evergreen Terrace |
| street2 | VARCHAR(200) | NULL | Apartment, suite, unit (optional) | Apt 3B |
| city | VARCHAR(100) | NOT NULL | City | Springfield |
| state_cd | CHAR(2) | NOT NULL | Two-letter US state code | IL |
| zip | CHAR(5) | NOT NULL | Five-digit ZIP code | 62701 |
| effective_date | DATE | NOT NULL | Date this address became active | 2021-03-15 |
| end_date | DATE | NULL | Date this address ended; NULL means currently active | NULL |

## Primary key
address_id

## Foreign keys / relationships
- `member_id` → `members.member_id`

## Naming conventions
- To get the current address: filter WHERE end_date IS NULL.
- `state_cd` is always uppercase two-letter USPS abbreviation.
