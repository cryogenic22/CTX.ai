# Data Quality Framework

## Overview

Data quality is a critical concern for the ShopStream platform. Poor data quality leads to incorrect pricing, failed deliveries, compliance violations, and degraded customer experience. This document describes the data quality framework including rule definitions, monitoring infrastructure, alerting thresholds, and remediation procedures.

## Data Quality Dimensions

### Accuracy
Data values must correctly represent the real-world entity they describe.
- Order total_amount must equal subtotal + tax_amount + shipping_amount - discount_amount
- Inventory available_quantity must not be negative
- Customer email must be a valid, deliverable email address
- Tax rates must match current jurisdiction regulations

### Completeness
Required fields must be populated with meaningful values.
- Orders must have at least one OrderLine
- Products must have at least one active ProductVariant
- Active merchants must have at least one MerchantStore and one Warehouse
- Invoices with status ISSUED must have a pdf_url

### Consistency
The same fact must not be contradicted across different sources.
- Customer email in the identity-service must match the data warehouse
- Order total in the order-management-service must match the Payment amount
- Inventory counts in the inventory-service must reconcile with warehouse physical counts

### Timeliness
Data must be current and available within defined SLAs.
- Real-time data (inventory, prices): updated within 500ms
- Near-real-time data (order status): updated within 5 seconds
- Analytics data: refreshed daily by 06:00 UTC
- Search index: products indexed within 15 minutes of creation/update

### Uniqueness
Entities must not have unintended duplicates.
- Customer email must be unique among active accounts
- Product SKU must be unique per merchant
- Invoice number must be unique per merchant
- Coupon code must be unique among active coupons

### Validity
Data must conform to defined formats and business rules.
- Phone numbers in E.164 format
- Dates in ISO 8601 format
- Currency codes in ISO 4217 format
- Country codes in ISO 3166-1 alpha-2 format

## Rule Severity Levels

### ERROR (Blocks Transaction)
- Applied at the application layer during data writes
- Transaction is rejected if the rule fails
- Customer or merchant receives an error message
- Logged immediately for monitoring
- Examples:
  - Order total calculation mismatch
  - Payment amount does not match order total
  - Negative inventory quantity
  - Duplicate primary keys

### WARNING (Logged, Does Not Block)
- Applied at the application layer or in batch processing
- Transaction proceeds but the issue is logged
- Aggregated in data quality dashboards
- Investigated within 24 hours if threshold exceeded
- Examples:
  - Tax calculation rounding difference >$0.01
  - Product with fewer than 3 images
  - Merchant fulfillment time above SLA
  - Inventory count discrepancy within 2%

### INFO (Monitoring Only)
- Informational signals tracked for trend analysis
- No immediate action required
- Reviewed in weekly data quality meetings
- Examples:
  - Customer profile completeness score
  - Search query zero-result rate
  - Cart abandonment rate

## Entity-Level Quality Rules

### Customer Entity
| Rule | Severity | Enforcement |
|------|----------|-------------|
| Email must be unique among active customers | ERROR | Application + DB constraint |
| Phone number must be E.164 format | WARNING | Application validation |
| Date of birth must be >=13 years ago | ERROR | Application validation |
| Loyalty points must not be negative | ERROR | Application + DB constraint |
| Email deliverability check (no bounces) | WARNING | Batch (weekly) |

### Order Entity
| Rule | Severity | Enforcement |
|------|----------|-------------|
| total_amount = subtotal + tax + shipping - discount | ERROR | Application validation |
| Must have at least one OrderLine | ERROR | Application validation |
| cancelled_at set when status is CANCELLED | ERROR | Application validation |
| placed_at < confirmed_at < shipped_at < delivered_at | ERROR | Application validation |
| Marketplace orders: parent_order_id set for sub-orders | WARNING | Batch (daily) |

### Payment Entity
| Rule | Severity | Enforcement |
|------|----------|-------------|
| Amount must match order total_amount | ERROR | Application validation |
| Currency must match order currency | ERROR | Application validation |
| gateway_transaction_id set for CAPTURED/SETTLED | ERROR | Application validation |
| fraud_score between 0 and 100 | ERROR | Application validation |
| Idempotency key must be unique | ERROR | DB constraint |

### Inventory Entity
| Rule | Severity | Enforcement |
|------|----------|-------------|
| available_quantity >= 0 | ERROR | Application + DB constraint |
| reserved_quantity >= 0 | ERROR | Application + DB constraint |
| variant_id + warehouse_id unique | ERROR | DB constraint |
| Discrepancy >10% triggers audit | WARNING | Batch (after reconciliation) |
| Last counted within 7 days | WARNING | Batch (daily) |

### Merchant Entity
| Rule | Severity | Enforcement |
|------|----------|-------------|
| Must have at least one MerchantStore | ERROR | Application validation |
| Commission rate between 0 and 1 | ERROR | Application validation |
| Tax ID valid for merchant's country | ERROR | Verification process |
| Average fulfillment >14 days triggers review | WARNING | Batch (daily) |

## Monitoring Infrastructure

### Real-Time Monitoring
- **Application-level checks**: Validation rules enforced on every write operation
- **Database constraints**: NOT NULL, UNIQUE, CHECK constraints as the last line of defense
- **Event-driven alerts**: Specific error patterns trigger immediate PagerDuty alerts
- **Metrics collection**: All validation failures are emitted as Datadog metrics

### Batch Monitoring (dbt Tests)
The data warehouse runs dbt tests daily at 04:00 UTC after the ETL pipeline completes:

**Schema Tests** (run on every table):
- `not_null` on primary keys and required fields
- `unique` on identifier columns
- `accepted_values` on enum columns
- `relationships` between foreign keys and parent tables

**Custom Data Tests**:
- `test_order_total_integrity`: Verify order total = sum of components
- `test_payment_order_match`: Verify payment amount matches order total
- `test_inventory_non_negative`: Check for negative inventory quantities
- `test_settlement_reconciliation`: Verify settlement amounts match order sums
- `test_pii_retention_compliance`: Ensure PII is scrubbed per retention policy
- `test_duplicate_customers`: Detect potential duplicate customer accounts
- `test_orphan_records`: Find records with broken foreign key references

### Dashboards

**Data Quality Overview** (Looker):
- Overall data quality score (weighted average across all rules)
- Trend chart: quality score over past 30 days
- Top 10 failing rules by occurrence count
- Quality score by entity type
- Quality score by data source

**Operational Quality** (Datadog):
- Real-time ERROR-severity validation failure rate
- Payment-order amount mismatch rate
- Inventory discrepancy alerts
- Search indexing lag

**Compliance Dashboard** (Looker):
- PII retention compliance rate (target: 100%)
- Right-to-erasure request fulfillment rate
- Audit log completeness rate
- Data classification coverage

## Alerting Thresholds

| Metric | Warning | Critical | Action |
|--------|---------|----------|--------|
| ERROR validation failures/hour | >50 | >200 | Page data platform on-call |
| Order total mismatches/day | >5 | >20 | Page payments team |
| Negative inventory records | >0 | >10 | Page inventory team |
| dbt test failures | >2 | >5 | Page data eng on-call |
| PII retention violations | >0 | >0 | Alert DPO immediately |
| Search index lag (minutes) | >30 | >60 | Page search team |
| Payment-order mismatch | >0 | >5 | Page payments team |

## Remediation Procedures

### Automated Remediation
- **Negative inventory**: The 5-minute reconciliation job auto-corrects negative quantities by setting to 0 and logging the correction
- **Stale search index**: Auto-triggered re-index when lag exceeds 30 minutes
- **Orphan records**: Daily cleanup job archives orphaned records (e.g., order lines without parent order)

### Manual Remediation
- **Settlement discrepancies**: Finance team reviews, creates adjustment_amount on the Settlement entity
- **Duplicate customers**: Customer service reviews flagged duplicates, initiates merge if confirmed
- **Incorrect tax rates**: Tax team updates TaxRule entries, triggers retroactive recalculation for affected orders within the past 24 hours
- **Data corruption**: Data platform team restores from point-in-time backup (PostgreSQL PITR, 7-day window)

### Escalation
- Data quality issues not resolved within the SLA are escalated to the data platform team lead
- Recurring issues (same rule failing >3 times in 30 days) trigger a root cause investigation
- Systemic issues are presented in the weekly engineering review for cross-team resolution

## Data Quality SLAs

| Dimension | Target | Measurement |
|-----------|--------|-------------|
| Overall quality score | >=99.5% | Daily (dbt tests) |
| ERROR rule compliance | 100% | Real-time |
| WARNING rule compliance | >=98% | Daily |
| dbt test pass rate | >=99% | Daily |
| PII retention compliance | 100% | Daily |
| Data freshness (analytics) | <6 hours | Continuous |
| Data freshness (storefront) | <500ms | Continuous |

## Quarterly Review Process

Every quarter, the data platform team conducts a comprehensive data quality review:
1. Review all failing rules from the past quarter
2. Identify new rules needed based on incidents and user feedback
3. Retire rules that are no longer relevant
4. Update severity levels based on business impact assessment
5. Present findings to engineering leadership
6. Update this document with any changes
