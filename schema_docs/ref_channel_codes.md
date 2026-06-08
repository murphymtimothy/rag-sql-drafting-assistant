# TABLE: ref_channel_codes

**Subject area:** Branch/channel
**Purpose:** Reference table of transaction channels (how a transaction or interaction was initiated).

## Columns

| Column | Type | Nullable | Description | Example |
|---|---|---|---|---|
| channel_cd | VARCHAR(10) | NOT NULL | Short code — primary key and FK target | BRANCH |
| channel_name | VARCHAR(100) | NOT NULL | Human-readable channel name | Branch Teller |
| is_digital | BIT | NOT NULL | 1 if the channel is digital/remote; 0 if in-person | 0 |
| description | VARCHAR(500) | NULL | Additional notes about the channel | NULL |

## Primary key
channel_cd

## Sample rows
BRANCH = Branch Teller (is_digital=0), ATM = ATM (is_digital=0), ONLINE = Online Banking (is_digital=1), MOBILE = Mobile App (is_digital=1), CARD_PRESENT = Card POS (is_digital=0), CARD_NOT_PRESENT = Card CNP/online (is_digital=1)

## Foreign keys / relationships

**Outbound:** *(none — reference/lookup table)*

**Referenced by (other tables → ref_channel_codes.channel_cd):**
- `transactions.channel_cd` (deposit postings)
- `card_transactions.channel_cd` (card transactions)

**Common join paths:**
- Resolve a transaction's channel name: `transactions` → `ref_channel_codes` or `card_transactions` → `ref_channel_codes` (channel_name, is_digital).
