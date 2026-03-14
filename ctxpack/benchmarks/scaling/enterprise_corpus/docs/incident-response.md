# Incident Response Playbook

## Overview

This document provides runbook procedures for common production incidents on the ShopStream platform. It covers incident classification, escalation paths, and step-by-step resolution procedures for the most frequently encountered issues. All incidents must be logged in the incident management system (PagerDuty) and post-incident reviews conducted for Severity 1 and 2 incidents.

## Incident Severity Levels

### Severity 1 (Critical)
- **Definition**: Complete platform outage or data loss affecting all customers
- **Examples**: Payment processing down, database cluster failure, security breach
- **Response time**: 5 minutes (pager)
- **Resolution target**: 1 hour
- **Communication**: Status page updated every 15 minutes, exec stakeholders notified
- **Post-incident**: Mandatory post-mortem within 48 hours

### Severity 2 (High)
- **Definition**: Major feature degradation affecting >10% of customers
- **Examples**: Search unavailable, webhook delivery failures >50%, inventory sync lag >1 hour
- **Response time**: 15 minutes (Slack alert)
- **Resolution target**: 4 hours
- **Communication**: Status page updated every 30 minutes
- **Post-incident**: Post-mortem within 1 week

### Severity 3 (Medium)
- **Definition**: Minor feature degradation or single-merchant issue
- **Examples**: Slow API responses (p99 >2s), single warehouse sync failure, image processing delays
- **Response time**: 1 hour (Slack notification)
- **Resolution target**: 24 hours
- **Communication**: Internal Slack updates

### Severity 4 (Low)
- **Definition**: Cosmetic or minor issues with workarounds available
- **Examples**: UI rendering glitch, non-critical email formatting, dashboard data delay
- **Response time**: Next business day
- **Resolution target**: 1 week

## Incident Response Procedures

### INC-001: Payment Processing Outage

**Symptoms**:
- Spike in Payment.status = FAILED
- Customer complaints about checkout failures
- Gateway health check failures

**Diagnosis**:
1. Check Stripe status page (status.stripe.com) and Adyen status page
2. Check payment-service health endpoint: `GET /health`
3. Review payment-service error logs for gateway timeout or 5xx errors
4. Check network connectivity between payment-service and gateway endpoints
5. Verify API keys are not expired or revoked

**Resolution**:
- If Stripe is down: Activate Adyen failover in payment-service config
  ```
  kubectl set env deployment/payment-service PAYMENT_GATEWAY_PRIMARY=adyen
  ```
- If both gateways are down: Activate queued payment mode (orders accepted, payment retried when gateway recovers)
- If network issue: Check VPC security groups and NAT gateway health
- If API key issue: Rotate keys via the gateway dashboard and update Kubernetes secrets

**Rollback**: Revert gateway config to Stripe primary once Stripe confirms recovery

**Impact**: All new orders cannot be processed. Existing authorized payments are unaffected.

### INC-002: Inventory Overselling

**Symptoms**:
- Merchants report orders for out-of-stock items
- available_quantity shows negative values
- Customer complaints about order cancellations due to stock unavailability

**Diagnosis**:
1. Query inventory records for negative available_quantity
2. Check inventory-service logs for concurrent update conflicts
3. Review the optimistic locking version increments for anomalies
4. Check if the reconciliation background job is running
5. Verify the advisory lock mechanism in PostgreSQL is functioning

**Resolution**:
1. Identify oversold orders (orders where variant stock is negative)
2. Contact affected merchants to confirm actual stock
3. If item truly out of stock: cancel oversold orders (most recent first), issue full refunds
4. If stock exists: correct inventory counts via admin API
5. Investigate root cause: usually a race condition during high traffic

**Prevention**:
- The 5-minute reconciliation job catches most overselling within one cycle
- For flash sales, enable "reservation mode" which uses stricter locking

### INC-003: Webhook Delivery Failure Spike

**Symptoms**:
- WebhookEvent delivery_status = RETRYING for >50% of recent events
- Merchant complaints about missing order notifications
- Alert on webhook delivery success rate dropping below 90%

**Diagnosis**:
1. Check webhook-service health and queue depth
2. Identify affected merchants (may be a specific merchant's endpoint down)
3. Review http_status_code on failed events (5xx = merchant server issue, timeout = network)
4. Check for certificate expiry on merchant endpoints
5. Verify webhook-service can reach external endpoints (network/firewall)

**Resolution**:
- If specific merchant: Contact merchant about their endpoint availability
- If widespread: Check webhook-service scaling (may need more workers)
- If DNS resolution failures: Check DNS resolver configuration
- If certificate issues: Verify CA trust store is up to date

**Merchant Communication**: If merchant endpoint is down for >4 hours, send proactive email notification.

### INC-004: Data Warehouse Sync Failure

**Symptoms**:
- Analytics dashboards showing stale data
- dbt job failures
- Snowflake connector errors

**Diagnosis**:
1. Check Snowflake connector status and error logs
2. Verify Snowflake account is accessible and not in maintenance
3. Check source database replication lag
4. Review dbt test results for data quality failures
5. Check if the daily snapshot job ran (02:00 UTC)

**Resolution**:
- If connector failure: Restart the Snowflake connector service
- If data quality failure: Review failing dbt tests, fix source data if needed
- If replication lag: Check PostgreSQL replication status and WAL backlog
- If Snowflake maintenance: Wait for maintenance window to complete, re-trigger sync

**Impact**: Analytics dashboards show data from last successful sync. No customer-facing impact.

### INC-005: Search Index Degradation

**Symptoms**:
- Slow search response times (>500ms)
- Missing products in search results
- Elasticsearch cluster health yellow or red

**Diagnosis**:
1. Check Elasticsearch cluster health: `GET /_cluster/health`
2. Check node disk usage (red cluster usually means disk >85%)
3. Review indexing lag (new products not appearing in search)
4. Check shard allocation and balance
5. Verify the product indexing pipeline is running

**Resolution**:
- If disk pressure: Expand EBS volumes or clean up old indices
- If unassigned shards: `POST /_cluster/reroute?retry_failed=true`
- If indexing lag: Check and restart the product-indexer service
- If cluster instability: Scale up data nodes

### INC-006: Customer PII Data Breach Suspicion

**Symptoms**:
- Unusual data access patterns in AuditLog
- Reports of customer data appearing externally
- Unauthorized bulk data exports detected
- Anomalous API key usage patterns

**IMMEDIATE ACTIONS** (do not wait for full diagnosis):
1. Alert the Security Team lead and DPO immediately
2. Revoke any suspicious API keys or user sessions
3. Enable enhanced audit logging on affected systems
4. Do NOT modify or delete any evidence (audit logs, access logs)

**Diagnosis**:
1. Review AuditLog for unusual EXPORT actions or bulk data reads
2. Identify the actor (user, API key, system account) involved
3. Determine the scope of potentially exposed data (which entities, which customers)
4. Review network logs for unusual outbound data transfers
5. Check if any admin accounts show signs of compromise

**Resolution**:
1. Contain: Disable compromised accounts/keys, rotate affected credentials
2. Assess: Determine number of affected customers and data types exposed
3. Report: Notify DPO within 1 hour; DPO determines if GDPR 72-hour notification applies
4. Notify: If required, notify affected customers and supervisory authority
5. Remediate: Fix the vulnerability, conduct security review, update access controls

**Legal Requirements**:
- GDPR: Report to supervisory authority within 72 hours if risk to data subjects
- PCI-DSS: If payment data involved, report to payment brands within 24 hours
- State breach laws: Vary by US state; legal team to advise

### INC-007: Merchant Settlement Discrepancy

**Symptoms**:
- Merchant disputes settlement amount
- Reconciliation report shows discrepancies
- Settlement net_amount doesn't match expected

**Diagnosis**:
1. Pull the settlement detail report (report_url field)
2. Reconcile order-by-order against the merchant's records
3. Check for timing issues (orders placed near period boundary)
4. Verify commission rate applied matches merchant agreement
5. Check for unaccounted refunds or chargebacks

**Resolution**:
- If timing issue: Explain settlement period boundaries, offer adjustment credit
- If commission rate wrong: Correct in merchant record, issue adjustment_amount on next settlement
- If missing orders: Investigate order-to-settlement mapping, add missing orders
- If chargeback not communicated: Share chargeback details with merchant

## Escalation Matrix

| Component | Primary On-Call | Secondary | Manager |
|-----------|----------------|-----------|---------|
| Payment Service | payments-oncall@shopstream.com | Platform Eng Lead | VP Engineering |
| Order Management | orders-oncall@shopstream.com | Platform Eng Lead | VP Engineering |
| Inventory | inventory-oncall@shopstream.com | Operations Lead | VP Operations |
| Search | search-oncall@shopstream.com | Data Eng Lead | VP Engineering |
| Data Platform | data-oncall@shopstream.com | Data Eng Lead | VP Engineering |
| Security | security@shopstream.com | CISO | CEO |
| Customer Data/GDPR | dpo@shopstream.com | Legal Team | General Counsel |

## Post-Incident Review Template

For Sev1 and Sev2 incidents, complete the following within the specified timeframe:

1. **Timeline**: Minute-by-minute account from detection to resolution
2. **Root Cause**: Specific technical cause (not "human error")
3. **Impact**: Number of affected customers, revenue impact, SLA violation
4. **Detection**: How was the incident detected? Could it have been detected sooner?
5. **Resolution**: Steps taken to resolve. Were they effective? What took the longest?
6. **Action Items**: Specific, assigned, time-bound improvements to prevent recurrence
7. **Lessons Learned**: What worked well? What should change?

All post-incident reviews are stored in Confluence and reviewed in the weekly engineering sync.
