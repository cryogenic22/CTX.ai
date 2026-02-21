# Entity: CUSTOMER

## Matching Rules

Customer matching is critical for data quality. The system uses a three-tier approach:

- Email is matched exactly (case-insensitive, trimmed)
- Phone numbers are normalised to E.164 format before comparison
- Name + address uses Jaro-Winkler similarity with threshold 0.92, requiring manual review

## Communication Preferences

All customers must have at least one communication channel. Default is email.

# Entity: ORDER

## Financial Rules

All monetary values must use DECIMAL(19,4). Never use FLOAT for financial data.

## Status Transitions

Orders follow a strict state machine: draft -> submitted -> processing -> shipped -> delivered.
Terminal states include: cancelled, returned.
Once submitted, line items cannot be edited.
