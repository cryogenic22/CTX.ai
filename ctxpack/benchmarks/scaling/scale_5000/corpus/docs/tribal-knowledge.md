# Tribal Knowledge & Known Issues

## Known Data Quality Issues
- SKU format is inconsistent across merchants; normalisation pipeline required
- "HCP" and "provider" are synonyms; canonical term is PROVIDER
- Legacy systems may use deprecated field names

## Retention Gotchas
> **Warning:** The 36-month anonymisation rule for churned providers must NOT be applied
> to providers with financial records. The 7-year regulatory retention overrides.

## Seasonal WAREHOUSE
- Seasonal warehouses are auto-deactivated at end of season
- Reactivation requires manual review by merchandising team
- Pre-order warehouses have different pricing rules
