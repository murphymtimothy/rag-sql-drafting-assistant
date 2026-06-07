# TABLE: card_accounts

**Subject area:** Cards
**Purpose:** Credit card accounts held by members — one row per card account.

## Columns

| Column | Type | Nullable | Description | Example |
|---|---|---|---|---|
| card_account_id | INT | NOT NULL | Surrogate primary key | 40001 |
| member_id | INT | NOT NULL | FK — the member who holds this card | 10042 |
| card_type_cd | VARCHAR(15) | NOT NULL | VISA_CLASSIC, VISA_PLATINUM, SECURED | VISA_PLATINUM |
| credit_limit | DECIMAL(15,2) | NOT NULL | Authorized credit limit | 5000.00 |
| available_credit | DECIMAL(15,2) | NOT NULL | Credit limit minus current balance | 3241.50 |
| opened_date | DATE | NOT NULL | Date the card account was opened | 2020-02-14 |
| status_cd | VARCHAR(10) | NOT NULL | Current card status; resolves against ref_status_codes (entity_type='CARD') | ACTIVE |

## Primary key
card_account_id

## Foreign keys / relationships
- `member_id` → `members.member_id`
- `status_cd` → `ref_status_codes.status_cd` (filter entity_type = 'CARD')
