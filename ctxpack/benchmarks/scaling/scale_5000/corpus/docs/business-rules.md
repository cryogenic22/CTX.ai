# Business Rules

## PROVIDER Matching Rules

PROVIDER records are matched using multiple strategies:
- **Email**: exact match, case-insensitive, trimmed whitespace
- **Phone**: normalised to E.164 format before comparison
- **Name + Address**: Jaro-Winkler similarity > 0.92 triggers manual review

All providers must have at least one communication channel. Default channel is email.

## PATIENT Financial Rules

All monetary values must use DECIMAL(19,4). Never use FLOAT for financial data.

### Status Flow
PATIENT follows: draft → submitted → processing → shipped → delivered.
Terminal states: cancelled, returned.

Once an patient reaches submitted status, line items cannot be edited.
