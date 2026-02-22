# Tribal Knowledge & Known Issues

## Known Data Quality Issues
- SKU format is inconsistent across merchants; normalisation pipeline required
- "purchase" and "order" are synonyms; canonical term is ORDER
- Legacy systems may use deprecated field names

## Retention Gotchas
> **Warning:** The 36-month anonymisation rule for churned orders must NOT be applied
> to orders with financial records. The 7-year regulatory retention overrides.

## Seasonal PAYMENT
- Seasonal payments are auto-deactivated at end of season
- Reactivation requires manual review by merchandising team
- Pre-order payments have different pricing rules
