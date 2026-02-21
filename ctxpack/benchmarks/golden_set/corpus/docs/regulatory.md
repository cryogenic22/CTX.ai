# Regulatory Requirements

## Data Retention

Financial transaction data must be retained for a minimum of 7 years per regulatory requirements.
This applies to all payment records and order financial details.

> **Warning:** The 7-year regulatory retention overrides any shorter entity-specific retention policies.

## PII Handling

All PII fields must be encrypted at rest and in transit.
Access to HIGHLY-RESTRICTED data (payment card numbers) requires additional authorization.

## Audit Trail

All changes to customer and payment data must be logged with:
- Timestamp (UTC)
- User/system making the change
- Before and after values
- Reason for change
