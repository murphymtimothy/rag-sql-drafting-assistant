# TABLE: loan_types

**Subject area:** Lending
**Purpose:** Reference table of loan product types offered (e.g., Auto, Personal, HELOC, Mortgage, Credit Builder).

## Columns

| Column | Type | Nullable | Description | Example |
|---|---|---|---|---|
| loan_type_cd | VARCHAR(10) | NOT NULL | Short code — primary key and FK target | AUTO |
| loan_type_name | VARCHAR(100) | NOT NULL | Human-readable name | Auto Loan |
| max_ltv | DECIMAL(5,4) | NULL | Maximum loan-to-value ratio; NULL if not collateral-based | 0.9000 |
| max_term_months | INT | NOT NULL | Maximum allowable term in months | 84 |
| is_secured | BIT | NOT NULL | 1 if the loan requires collateral | 1 |

## Primary key
loan_type_cd

## Foreign keys / relationships

**Outbound:** *(none — reference/lookup table)*

**Referenced by (other tables → loan_types.loan_type_cd):**
- `loan_applications.loan_type_cd`
- `loans.loan_type_cd`

**Common join paths:**
- Resolve a loan's or application's product name and terms: `loans` → `loan_types` or `loan_applications` → `loan_types`.
