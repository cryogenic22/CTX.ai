# ShopStream Platform Architecture

## Overview

ShopStream is a cloud-native marketplace platform built on a microservice architecture running on AWS. The platform processes approximately 500,000 orders per day across 22 supported currencies and 15 countries. This document provides a high-level overview of the technical architecture, service boundaries, data flow, and infrastructure for the data platform team's reference.

## Service Architecture

### Core Services
The platform consists of 18 microservices, each owning its domain data and exposing APIs for inter-service communication.

| Service | Domain | Database | Language |
|---------|--------|----------|----------|
| identity-service | Customers, Addresses, Auth | PostgreSQL 15 | Go |
| order-management-service | Orders, OrderLines | PostgreSQL 15 | Go |
| payment-service | Payments, Refunds, PaymentMethods | PostgreSQL 15 (encrypted) | Go |
| catalog-service | Products, Variants, Categories | PostgreSQL 15 + Elasticsearch | Python |
| merchant-service | Merchants, Stores | PostgreSQL 15 | Go |
| inventory-service | Inventory, Warehouses | PostgreSQL 15 | Go |
| fulfillment-service | Shipments, Tracking | PostgreSQL 15 | Go |
| billing-service | Invoices, Settlements, Fees | PostgreSQL 15 | Go |
| subscription-service | Subscriptions, Plans | PostgreSQL 15 | Python |
| promotions-service | Coupons, Discounts | PostgreSQL 15 | Python |
| cart-service | Carts | Redis + PostgreSQL | Go |
| search-service | Search queries, Autocomplete | Elasticsearch | Python |
| reviews-service | Reviews | PostgreSQL 15 | Python |
| notification-service | Notifications, Templates | PostgreSQL 15 + SQS | Python |
| webhook-service | Webhook events, Subscriptions | PostgreSQL 15 + SQS | Go |
| media-service | Product images, Assets | S3 + PostgreSQL | Python |
| tax-service | Tax rules, Calculations | PostgreSQL 15 | Go |
| audit-service | Audit logs | Amazon Timestream | Go |

### Inter-Service Communication
- **Synchronous**: gRPC for internal service-to-service calls (low latency, strong typing)
- **Asynchronous**: Amazon SQS for event-driven workflows (order lifecycle, notifications, webhooks)
- **API Gateway**: Kong API Gateway for external merchant/customer API requests (rate limiting, authentication, routing)

### Event Bus
All domain events are published to Amazon SQS/SNS topics:
- `order-events`: order.created, order.updated, order.cancelled
- `payment-events`: payment.authorized, payment.captured, payment.failed
- `inventory-events`: inventory.updated, inventory.low_stock
- `fulfillment-events`: shipment.created, shipment.delivered
- `customer-events`: customer.created, customer.updated, customer.deleted
- `catalog-events`: product.created, product.updated, product.archived

Services subscribe to relevant topics and process events asynchronously. The webhook-service subscribes to all merchant-relevant events and forwards them to merchant endpoints.

## Data Infrastructure

### Source Databases
- Each service owns its PostgreSQL database (logical isolation)
- PostgreSQL 15 running on Amazon RDS with Multi-AZ deployment
- Encryption at rest (AES-256 via AWS KMS)
- Point-in-time recovery: 7-day backup window
- Read replicas for reporting queries (do not query production primaries)

### Data Warehouse
- **Platform**: Snowflake (Enterprise edition)
- **Ingestion**: Debezium CDC → Kafka → Snowflake Snowpipe (near-real-time)
- **Transformation**: dbt Core running on Airflow (scheduled daily at 02:00 UTC)
- **Layers**:
  - `raw`: CDC mirror of source databases (append-only)
  - `staging`: Cleaned and typed source data
  - `intermediate`: Business logic transformations and joins
  - `marts`: Analytics-ready tables for BI tools
  - `compliance`: PII-scrubbed views for broad access

### Search Infrastructure
- **Engine**: Elasticsearch 8.x (3-node cluster)
- **Use cases**: Product search, autocomplete, search analytics
- **Indexing**: Catalog changes are pushed to Elasticsearch via the product-indexer worker
- **Index refresh**: 1 second (near-real-time)
- **Retention**: Active index only; no historical search data in Elasticsearch

### Caching Layer
- **Redis Cluster**: 6 nodes (3 primary, 3 replica)
- **Use cases**: Cart storage, session tokens, inventory availability cache, rate limit counters
- **Eviction**: LRU with TTL (carts: 30 days, sessions: 7 days, inventory cache: 60 seconds)

### Object Storage
- **S3**: Product images (originals and processed variants), invoice PDFs, settlement reports, data exports
- **CloudFront CDN**: Serves product images and static assets globally
- **Lifecycle**: Original images to S3 Glacier after 1 year; invoices retained in S3 Standard for 10 years

## Deployment and Infrastructure

### Container Orchestration
- Amazon EKS (Kubernetes 1.28)
- Services deployed as Kubernetes Deployments with HPA (Horizontal Pod Autoscaler)
- Minimum 2 pods per service in production (3 for critical services: payment, order, identity)
- Rolling deployments with readiness probes

### Networking
- VPC with private subnets for services, public subnets for load balancers
- Network segmentation: payment-service CDE in isolated subnet (PCI-DSS requirement)
- AWS PrivateLink for database and S3 access (no internet traversal for internal traffic)
- WAF (Web Application Firewall) on the API Gateway for DDoS protection and OWASP Top 10

### Monitoring and Observability
- **Metrics**: Datadog (application metrics, infrastructure metrics, custom dashboards)
- **Logging**: CloudWatch Logs → Datadog Log Management (structured JSON logging)
- **Tracing**: Datadog APM with distributed trace IDs across service calls
- **Alerting**: PagerDuty integration with Datadog for on-call rotation
- **Status Page**: statuspage.shopstream.com (public)

### CI/CD
- GitHub Actions for build and test
- Docker images pushed to Amazon ECR
- ArgoCD for GitOps-based Kubernetes deployments
- Staging environment mirrors production (scaled down)
- Canary deployments for high-risk changes (payment-service, order-management-service)

## Data Flow: Order Placement

The following illustrates the data flow when a customer places an order:

1. **Customer** → **API Gateway** → **cart-service**: Checkout initiated
2. **cart-service** → **identity-service**: Validate customer and addresses
3. **cart-service** → **catalog-service**: Verify product availability and prices
4. **cart-service** → **inventory-service**: Reserve stock (optimistic lock)
5. **cart-service** → **tax-service**: Calculate taxes
6. **cart-service** → **promotions-service**: Apply coupons and discounts
7. **cart-service** → **order-management-service**: Create order and order lines
8. **order-management-service** → **SQS** (order.created): Publish event
9. **payment-service** (subscribed to order.created): Process payment authorization
10. **payment-service** → **Stripe/Adyen**: External gateway call
11. **payment-service** → **SQS** (payment.authorized): Publish result
12. **order-management-service** (subscribed to payment.authorized): Update order → CONFIRMED
13. **notification-service** (subscribed to order.created): Send confirmation email
14. **webhook-service** (subscribed to order.created): Deliver merchant webhook
15. **audit-service** (subscribed to all events): Log audit trail entries

## Capacity and Scale

### Current Scale (as of 2025-Q4)
- ~500,000 orders/day peak
- ~5 million active customers
- ~50,000 active merchants
- ~8 million product SKUs
- ~2 million webhook events/day
- ~50 million API requests/day

### Growth Projections
- 30% YoY order volume growth
- 40% YoY merchant growth
- Infrastructure auto-scales via HPA; capacity planning reviewed quarterly

## Disaster Recovery

### RPO and RTO
- **Recovery Point Objective (RPO)**: <5 minutes (Debezium CDC replication lag)
- **Recovery Time Objective (RTO)**: <1 hour for individual services, <4 hours for full platform
- **Multi-AZ**: All databases and services run across 3 availability zones
- **Cross-region**: Warm standby in us-west-2 (primary: us-east-1); switchover tested quarterly

### Backup Strategy
- PostgreSQL: Automated daily snapshots + continuous WAL archiving (7-day PITR)
- Elasticsearch: Daily snapshots to S3 (14-day retention)
- Redis: AOF persistence + hourly RDB snapshots
- S3: Cross-region replication for critical buckets (images, invoices)
