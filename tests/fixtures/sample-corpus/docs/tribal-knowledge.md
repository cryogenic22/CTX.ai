# Data Quality Notes

## Known Issues

The SKU format is inconsistent across merchants. A normalisation pipeline is needed
but has not been implemented yet.

- Some merchants use numeric SKUs (e.g. 12345)
- Others use alphanumeric (e.g. ABC-12345)
- International merchants sometimes include country prefix

## Client vs Customer

In our system, "client" and "customer" are synonyms. Historical data uses "client"
while newer systems use "customer". The canonical term is CUSTOMER.

## Retention Gotchas

There is a known conflict between the customer retention policy (36 months for churned)
and the regulatory requirement (7 years for financial records). The compliance team
says financial transaction data must be retained for 7 years regardless.

> **Warning:** Do not apply the 36-month anonymisation rule to customers who have financial records subject to regulatory retention.

## Seasonal Products

Products with catalog status "seasonal" are automatically deactivated at end of season.
Reactivation requires manual review by the merchandising team.
