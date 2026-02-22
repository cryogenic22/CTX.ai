# Regulatory Compliance

## Data Retention
- Financial transaction data must be retained for a minimum of **7 years** (84 months)
- This regulatory requirement **overrides** any shorter entity-specific retention policies
- All retention policies must be auditable

## PII Handling
- All PII fields must be encrypted at rest and in transit
- HIGHLY-RESTRICTED data (payment card numbers, bank accounts) requires additional authorization
- Access to PII must be logged in the audit trail

## Audit Trail Requirements
Every change to ORDER or ACCOUNT data must log:
- Timestamp (UTC)
- User or system that made the change
- Before and after values
- Reason for the change
