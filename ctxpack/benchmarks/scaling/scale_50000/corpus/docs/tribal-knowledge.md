# Tribal Knowledge & Known Issues

## Known Data Quality Issues
- SKU format is inconsistent across merchants; normalisation pipeline required
- "facility" and "warehouse" are synonyms; canonical term is WAREHOUSE
- Legacy systems may use deprecated field names

## Retention Gotchas
> **Warning:** The 36-month anonymisation rule for churned warehouses must NOT be applied
> to warehouses with financial records. The 7-year regulatory retention overrides.

## Seasonal ACCOUNT
- Seasonal accounts are auto-deactivated at end of season
- Reactivation requires manual review by merchandising team
- Pre-order accounts have different pricing rules
