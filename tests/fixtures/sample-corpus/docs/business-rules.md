# Entity: CUSTOMER

## Matching Rules

Customer matching is critical for data quality. The system uses a three-tier approach:

- Email is matched exactly (case-insensitive, trimmed)
- Phone numbers are normalised to E.164 format before comparison
- Name + address uses Jaro-Winkler similarity with a threshold of 0.92, requiring manual review

## Tier System

Customers are classified into tiers based on lifetime value:
- Bronze: $0-$999
- Silver: $1000-$4999
- Gold: $5000-$19999
- Platinum: $20000+

> **Warning:** Tier downgrades are not automatic. Manual review required for any downgrade.

## Communication Preferences

All customers must have at least one communication channel. Default is email.

# Entity: ORDER

## Financial Rules

All monetary values must use DECIMAL(19,4) — never use FLOAT for financial data.

Orders above $10,000 are flagged for manual review. Orders above $50,000 trigger auto-hold and alert.

> **Note:** Financial field precision was increased from DECIMAL(10,2) in Q3 2025.
