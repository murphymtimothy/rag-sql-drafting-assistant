# TABLE: card_rewards

**Subject area:** Cards
**Purpose:** Reward point ledger for card accounts — one row per point-earning or point-redemption event. Points balance is tracked as a running total.

## Columns

| Column | Type | Nullable | Description | Example |
|---|---|---|---|---|
| reward_id | INT | NOT NULL | Surrogate primary key | 9900001 |
| card_account_id | INT | NOT NULL | FK — the card account these points belong to | 40001 |
| transaction_date | DATE | NOT NULL | Date the point event occurred | 2026-05-20 |
| points_earned | INT | NOT NULL | Points earned in this event; 0 for redemption-only rows | 87 |
| points_redeemed | INT | NOT NULL | Points redeemed in this event; 0 for earn-only rows | 0 |
| points_balance | INT | NOT NULL | Running points balance after this event | 4321 |
| expiry_date | DATE | NULL | Date points expire; NULL means points do not expire | NULL |

## Primary key
reward_id

## Foreign keys / relationships
- `card_account_id` → `card_accounts.card_account_id`

## Naming conventions
- To get the current points balance for a card: SELECT TOP 1 points_balance ORDER BY transaction_date DESC, reward_id DESC.
- Points are issued at 1 point per dollar of purchases (is_credit=0 card_transactions).
