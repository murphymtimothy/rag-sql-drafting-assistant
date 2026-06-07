# TABLE: card_transactions

**Subject area:** Cards
**Purpose:** Individual card purchase, payment, and refund transactions posted to card accounts.

## Columns

| Column | Type | Nullable | Description | Example |
|---|---|---|---|---|
| card_txn_id | INT | NOT NULL | Surrogate primary key | 7700881 |
| card_account_id | INT | NOT NULL | FK — the card account this transaction posted to | 40001 |
| txn_date | DATETIME | NOT NULL | Date and time the transaction posted | 2026-05-20 13:44:00 |
| merchant_name | VARCHAR(255) | NOT NULL | Merchant name from the card network | SPRINGFIELD GROCER |
| merchant_category_cd | CHAR(4) | NOT NULL | ISO MCC code (e.g., 5411 = Grocery Stores) | 5411 |
| amount | DECIMAL(15,2) | NOT NULL | Transaction amount — always positive | 87.54 |
| is_credit | BIT | NOT NULL | 0 = purchase/charge; 1 = payment or refund | 0 |
| channel_cd | VARCHAR(10) | NOT NULL | Channel used; resolves against ref_channel_codes | CARD_PRESENT |

## Primary key
card_txn_id

## Foreign keys / relationships
- `card_account_id` → `card_accounts.card_account_id`
- `channel_cd` → `ref_channel_codes.channel_cd`
