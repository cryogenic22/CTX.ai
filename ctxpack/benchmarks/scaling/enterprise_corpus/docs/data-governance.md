# ShopStream Data Governance Framework

## Overview

This document defines the data governance policies, procedures, and standards for the ShopStream e-commerce platform. It covers data classification, retention policies, access controls, compliance requirements, and data lifecycle management. All team members with access to ShopStream data must be familiar with this framework and complete annual data governance training.

## Data Classification Tiers

ShopStream classifies all data into four sensitivity tiers. Each tier carries specific handling requirements for storage, access, transmission, and retention.

### Tier 1: Public Data
- Product catalog information (titles, descriptions, prices, images)
- Category taxonomy
- Publicly visible merchant information (display name, rating)
- Platform terms of service and policies
- **Handling**: No restrictions on access or transmission. Cached aggressively by CDN.

### Tier 2: Internal Data
- Order volumes and aggregate statistics
- Internal configuration parameters
- Non-PII operational data (system metrics, error rates)
- Warehouse locations and capacity
- **Handling**: Accessible to authenticated ShopStream employees. Not shared externally without approval. Encrypted in transit (TLS 1.3).

### Tier 3: Confidential Data
- Merchant financial details (commission rates, settlement amounts, bank information)
- Merchant cost prices and margin data
- Internal analytics and business intelligence reports
- API keys and integration credentials
- **Handling**: Encrypted at rest (AES-256) and in transit. Access restricted to authorized roles. Logged in audit trail. Requires manager approval for export.

### Tier 4: Restricted Data (PII and Financial)
- Customer personal information (name, email, phone, date of birth)
- Customer addresses and location data
- Payment card data (tokenized; raw card numbers never stored)
- Health-related data for age-restricted product verification
- Bank account numbers and tax identification numbers
- **Handling**: Encrypted at rest (AES-256) with customer-managed keys for payment data. Access restricted to minimum necessary roles. All access logged. Subject to data retention limits and right-to-erasure. Requires DPO approval for bulk access or export.

## Data Retention Policies

Data retention is governed by the principle of minimal data retention: data is retained only as long as necessary for its stated purpose or as required by law. The following table summarizes entity-level retention periods:

### Customer Domain
| Entity | Full Retention | PII Scrub Window | Legal Basis |
|--------|---------------|-------------------|-------------|
| Customer | 7 years from last activity | 30 days after deletion | Contractual + financial reporting |
| CustomerAddress | 7 years (follows Customer) | Immediate on deletion | Contractual |
| PaymentMethod | 7 years for audit | Immediate on deletion | PCI-DSS |
| UserSession | 1 year | 90 days | Security monitoring |
| Review | Product lifetime + 2 years | On archival | Contractual |
| Wishlist | Follows Customer | On deletion | Consent |
| SearchQuery | 2 years | 90 days | Legitimate interest |

### Order Domain
| Entity | Full Retention | PII Scrub Window | Legal Basis |
|--------|---------------|-------------------|-------------|
| Order | 7 years from order date | 2 years | Financial reporting |
| OrderLine | 7 years (follows Order) | 2 years | Financial reporting |
| Cart | 1 year (converted), 90 days (abandoned) | On expiry | Legitimate interest |
| ReturnRequest | 5 years | 2 years | Consumer protection |

### Payment Domain
| Entity | Full Retention | PII Scrub Window | Legal Basis |
|--------|---------------|-------------------|-------------|
| Payment | 10 years | 3 years | PCI-DSS + financial regulations |
| Refund | 10 years | 3 years | Financial regulations |
| Invoice | 10 years | Full period (tax requirement) | Tax compliance |

### Merchant Domain
| Entity | Full Retention | PII Scrub Window | Legal Basis |
|--------|---------------|-------------------|-------------|
| Merchant | 10 years after termination | 5 years after termination | Financial + contractual |
| Settlement | 10 years | N/A | Financial regulations |
| PlatformFee | 10 years | N/A | Financial regulations |

### Platform Domain
| Entity | Full Retention | PII Scrub Window | Legal Basis |
|--------|---------------|-------------------|-------------|
| AuditLog | 7 years (10 for security) | 3 years | SOC 2 + GDPR accountability |
| Notification | 2 years | 90 days | Operational |
| WebhookEvent | 90 days | On deletion | Operational |

**Important Note**: The retention period for Customer records is 7 years from the last order date or account deletion. However, the Payment entity has a 10-year retention period due to PCI-DSS and financial regulations. This means payment-related PII may be retained longer than other customer PII. This discrepancy is intentional and documented in the DPA (Data Processing Agreement).

## PII Handling Procedures

### Identification
PII fields are classified into the following categories in entity definitions:
- **DIRECT_IDENTIFIER**: Name, email, phone, address — can directly identify an individual
- **QUASI_IDENTIFIER**: Date of birth, ZIP code, city — can identify when combined
- **FINANCIAL**: Card numbers, bank accounts, tax IDs — financial PII with additional PCI-DSS requirements
- **ONLINE_IDENTIFIER**: IP address, device fingerprint, cookies — digital tracking identifiers
- **FREETEXT**: Free-form text fields that may contain PII (order notes, review text)
- **BEHAVIORAL**: Search queries, browsing patterns — behavioral data that may be PII under GDPR

### Collection
- PII collection must have a documented legal basis (consent, contractual necessity, legal obligation, or legitimate interest)
- Marketing consent must be explicitly opted-in (not pre-checked)
- The purpose of collection must be stated in the privacy policy
- Collect the minimum PII necessary for the stated purpose

### Storage
- All PII is encrypted at rest using AES-256
- Payment card data uses tokenization via Stripe/Adyen; raw card numbers never touch ShopStream systems
- PII fields are tagged in the data catalog with pii: true and pii_category
- Database columns containing PII are documented in the entity YAML definitions

### Access
- PII access follows the principle of least privilege
- Customer service agents can view customer PII necessary for their role
- Engineers access PII only through approved tools with audit logging
- Bulk PII access (exports, analytics queries returning >100 records) requires DPO approval
- All PII access is logged in the AuditLog entity

### Scrubbing
- PII scrubbing is performed by the automated data lifecycle service running daily
- Scrubbing replaces PII values with NULL or anonymized values (e.g., email becomes SHA-256 hash)
- Scrubbed records retain non-PII fields for aggregate reporting
- Scrubbing actions are logged in the audit trail with actor_type: SYSTEM

### Right to Erasure (GDPR Article 17)
- Customers can request account deletion through the account settings page or by contacting support
- Deletion requests are processed within 30 days per GDPR requirements
- Account deletion triggers: (1) soft-delete with deleted_at timestamp, (2) PII nullification within 30 days, (3) all active sessions are terminated, (4) all saved payment methods are revoked
- Order records and payment records are retained (with PII scrubbed) for financial reporting obligations
- The customer is notified via email when deletion is complete

## Compliance Framework

### GDPR (General Data Protection Regulation)
- Applicable to all EU/EEA customer data
- Data Processing Agreements (DPAs) in place with all processors
- Privacy Impact Assessments (PIAs) required for new data processing activities
- Data Protection Officer (DPO) appointed and accessible via dpo@shopstream.com
- Cross-border transfer safeguards: Standard Contractual Clauses (SCCs) for US-EU transfers

### PCI-DSS Level 1
- Annual on-site audit by Qualified Security Assessor (QSA)
- Quarterly network vulnerability scans by Approved Scanning Vendor (ASV)
- Payment data scope limited to the payment-service and its database
- Cardholder data environment (CDE) is network-segmented from other systems
- Tokenization eliminates card numbers from ShopStream's PCI scope for most services

### CCPA (California Consumer Privacy Act)
- Right to know: customers can request all data collected about them
- Right to delete: covered by GDPR deletion process (same workflow)
- Right to opt-out of sale: ShopStream does not sell personal information
- Financial incentive disclosure: loyalty program benefits are disclosed in privacy policy

### SOC 2 Type II
- Annual audit covering security, availability, confidentiality, processing integrity, and privacy
- Continuous monitoring via automated compliance checks
- Audit log retention (7 years) supports audit evidence requirements

## Data Quality Standards

### Ownership
Each entity has a designated golden_source system that is the authoritative source of truth. Data quality issues must be reported to and resolved by the owning team:

- **identity-service**: Customer, CustomerAddress
- **order-management-service**: Order, OrderLine
- **payment-service**: Payment, Refund, PaymentMethod
- **catalog-service**: Product, ProductVariant, Category
- **merchant-service**: Merchant, MerchantStore
- **inventory-service**: Inventory
- **fulfillment-service**: Shipment, ShipmentTracking
- **billing-service**: Invoice, Settlement, PlatformFee

### Monitoring
- Data quality rules are defined per entity in the entity YAML definitions
- Rules are enforced at two levels: (1) application-level validation on write, (2) batch dbt tests on the data warehouse
- Severity levels: ERROR (blocks transaction), WARNING (logged, does not block)
- Quality dashboards are maintained in Looker and reviewed weekly by the data platform team
- SLA: ERROR-severity data quality issues must be investigated within 4 hours

### Reconciliation
- Daily reconciliation between source systems and the data warehouse
- Payment amounts are reconciled with gateway records monthly
- Inventory counts are reconciled with physical counts weekly
- Settlement amounts are reconciled with bank statements per settlement cycle

## Data Lifecycle Automation

The data lifecycle service (`shopstream-data-lifecycle`) runs daily at 02:00 UTC and performs:

1. **PII Scrubbing**: Identifies records past their PII retention window and nullifies PII fields
2. **Record Archival**: Moves records past their retention period to cold storage (S3 Glacier)
3. **Hard Deletion**: Permanently deletes records past their archival retention period (retention + 2 years)
4. **Audit**: Logs all scrubbing, archival, and deletion actions in the audit trail
5. **Reporting**: Generates a daily data lifecycle report sent to the data governance Slack channel

## Change Management

Changes to data governance policies require:
1. Proposal document reviewed by the data platform team
2. Privacy Impact Assessment if the change affects PII handling
3. Legal review if the change affects compliance obligations
4. DPO sign-off for changes to retention periods or PII handling
5. 30-day notice to affected teams before implementation
6. Documentation update in this governance framework and entity YAML definitions
