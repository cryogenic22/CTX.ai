# API and Integration Guide

## Overview

The ShopStream REST API provides merchants with programmatic access to manage their catalog, process orders, update inventory, and configure integrations. This document covers API authentication, endpoints, rate limiting, webhook configuration, and best practices for building reliable integrations.

## API Authentication

### API Keys
Each merchant can generate multiple API keys through the Merchant Portal (Settings > API Keys) or via the API. Each key consists of:
- **Public key**: Used in the `X-API-Key` header for all requests. Format: `sk_live_XXXXXXXXXXXXXXXXXXXX` (production) or `sk_test_XXXXXXXXXXXXXXXXXXXX` (sandbox).
- **Secret key**: Used to generate HMAC-SHA256 request signatures. Displayed only once at creation time; stored as a bcrypt hash in the APIKey entity.

### Request Signing
All mutating API requests (POST, PUT, DELETE) must include a signature:
```
X-API-Key: sk_live_your_public_key
X-Signature: HMAC-SHA256(secret_key, timestamp + method + path + body)
X-Timestamp: 1710307200
```
- Signatures are validated within a 5-minute window to prevent replay attacks
- GET requests do not require signatures (but must include X-API-Key)

### Scopes
API keys are created with specific scopes that restrict which endpoints they can access:
- `catalog:read` — View products, variants, categories, images
- `catalog:write` — Create, update, archive products and variants
- `orders:read` — View orders, order lines, shipments
- `orders:write` — Update order status, create shipments
- `inventory:read` — View stock levels
- `inventory:write` — Update stock levels, manage warehouse inventory
- `customers:read` — View customer information for orders (limited to merchant's customers)
- `payments:read` — View payment and settlement information
- `webhooks:manage` — Configure webhook subscriptions
- `analytics:read` — Access merchant analytics dashboards

Keys with insufficient scopes receive HTTP 403 Forbidden.

### Sandbox vs. Production
- **Sandbox** (sk_test_XXX): Isolated environment for testing. No real payments processed. Test card numbers available. Data is reset weekly.
- **Production** (sk_live_XXX): Live environment. Real payments, real inventory, real customer data.

Sandbox and production share the same API endpoints; the key prefix determines which environment is used.

## Rate Limiting

### Limits by Merchant Tier
| Tier | Requests/Minute | Burst (10-second window) |
|------|----------------|--------------------------|
| Standard | 100 | 30 |
| Premium | 500 | 150 |
| Enterprise | 2,000 | 600 |

### Rate Limit Headers
Every API response includes rate limit headers:
```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 87
X-RateLimit-Reset: 1710307260
```

### Exceeding Rate Limits
- HTTP 429 Too Many Requests returned
- `Retry-After` header indicates when the client should retry (in seconds)
- Consistently exceeding limits may result in temporary throttling or API key suspension
- For burst traffic needs, contact the partnerships team to discuss Enterprise tier

### Separate Limits for Heavy Endpoints
- Inventory bulk updates: 10 requests/minute, max 1,000 records per request
- Product image uploads: 30 requests/minute, max 20MB per image
- Analytics queries: 20 requests/minute

## Core API Endpoints

### Products
- `GET /v1/products` — List products (paginated, filterable by status, category, date range)
- `GET /v1/products/{product_id}` — Get product details with variants
- `POST /v1/products` — Create a new product
- `PUT /v1/products/{product_id}` — Update product details
- `DELETE /v1/products/{product_id}` — Archive product (soft delete)

### Product Variants
- `GET /v1/products/{product_id}/variants` — List variants
- `POST /v1/products/{product_id}/variants` — Create variant
- `PUT /v1/variants/{variant_id}` — Update variant
- `DELETE /v1/variants/{variant_id}` — Deactivate variant

### Orders
- `GET /v1/orders` — List orders (paginated, filterable by status, date range, customer)
- `GET /v1/orders/{order_id}` — Get order details with lines
- `PUT /v1/orders/{order_id}/status` — Update order status (PROCESSING, SHIPPED, etc.)
- `POST /v1/orders/{order_id}/shipments` — Create shipment for order
- `POST /v1/orders/{order_id}/cancel` — Cancel order (if status allows)

### Inventory
- `GET /v1/inventory` — List inventory levels (filterable by variant, warehouse)
- `PUT /v1/inventory/{inventory_id}` — Update inventory quantities
- `POST /v1/inventory/bulk` — Bulk inventory update
- `POST /v1/inventory/reconcile` — Submit physical count reconciliation

### Webhooks
- `GET /v1/webhooks` — List webhook subscriptions
- `POST /v1/webhooks` — Create webhook subscription
- `PUT /v1/webhooks/{webhook_id}` — Update webhook endpoint or events
- `DELETE /v1/webhooks/{webhook_id}` — Delete webhook subscription
- `POST /v1/webhooks/{webhook_id}/test` — Send a test event to the endpoint

## Webhook Events

### Available Event Types
| Event | Trigger | Payload |
|-------|---------|---------|
| `order.created` | New order placed with the merchant | Full Order object with lines |
| `order.updated` | Order status change | Full Order object with previous_status |
| `order.cancelled` | Order cancelled | Full Order object with cancellation_reason |
| `payment.captured` | Payment captured for merchant's order | Payment object |
| `payment.failed` | Payment failed | Payment object with failure_reason |
| `shipment.created` | New shipment created | Shipment object |
| `shipment.delivered` | Shipment delivered | Shipment object with delivery details |
| `inventory.low_stock` | Stock below reorder threshold | Inventory object with variant details |
| `refund.completed` | Refund processed | Refund object |
| `review.created` | New review on merchant's product | Review object |
| `subscription.renewed` | Product subscription renewed | Subscription object |
| `subscription.cancelled` | Subscription cancelled | Subscription object |

### Webhook Payload Format
```json
{
  "event_id": "evt_550e8400-e29b-41d4-a716-446655440000",
  "event_type": "order.created",
  "api_version": "2025-01-15",
  "created_at": "2025-03-15T14:30:00Z",
  "data": {
    "order_id": "ord_...",
    "order_number": "US-20250315-000142",
    "status": "CONFIRMED",
    ...
  }
}
```

### Webhook Delivery
- HTTPS only (HTTP endpoints are rejected)
- POST request with JSON body
- Content-Type: application/json
- Includes `X-ShopStream-Signature` header for payload verification
- Expected response: HTTP 2xx within 5 seconds (timeout)
- Retry policy: 8 attempts over 48 hours (immediately, 1min, 5min, 30min, 2hr, 8hr, 24hr, 48hr)
- After all retries exhausted: event marked as FAILED, merchant notified via email

### Signature Verification
Merchants should verify webhook signatures to ensure payloads are authentic:
```
expected_signature = HMAC-SHA256(webhook_secret, raw_request_body)
received_signature = request.headers['X-ShopStream-Signature']
assert constant_time_compare(expected_signature, received_signature)
```

### Idempotency
- Each webhook event has a unique event_id (UUID)
- Merchants should store processed event_ids and skip duplicates
- Retries send the same event_id, so idempotency handling prevents duplicate processing

## Common Integration Patterns

### Inventory Sync with ERP
1. **Initial sync**: Bulk upload current stock levels via `POST /v1/inventory/bulk`
2. **Ongoing sync (push)**: ERP pushes stock changes to ShopStream API as they happen
3. **Ongoing sync (pull)**: Configure `inventory.low_stock` webhook; ERP triggers reorder
4. **Reconciliation**: Weekly `POST /v1/inventory/reconcile` with physical count data

### Order Processing with WMS
1. Subscribe to `order.created` webhook
2. On new order: create pick-pack task in WMS
3. When picked and packed: call `POST /v1/orders/{id}/shipments` with tracking number
4. ShopStream automatically updates order status and notifies customer

### Catalog Sync from Product Information Management (PIM)
1. PIM pushes product creates/updates via `POST /v1/products` and `PUT /v1/products/{id}`
2. Image upload via `POST /v1/products/{id}/images` with multipart/form-data
3. Category assignment via product update payload
4. Variant creation via `POST /v1/products/{id}/variants`

## Error Handling

### HTTP Status Codes
| Code | Meaning | Action |
|------|---------|--------|
| 200 | Success | Process response |
| 201 | Created | Resource successfully created |
| 400 | Bad Request | Fix request payload (validation errors in response body) |
| 401 | Unauthorized | Check API key |
| 403 | Forbidden | Check API key scopes |
| 404 | Not Found | Verify resource ID |
| 409 | Conflict | Optimistic locking conflict; re-read and retry |
| 422 | Unprocessable Entity | Business logic error (details in response body) |
| 429 | Rate Limited | Wait per Retry-After header |
| 500 | Internal Server Error | Retry with exponential backoff |
| 503 | Service Unavailable | Retry with exponential backoff |

### Error Response Format
```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Product title must not exceed 500 characters",
    "field": "title",
    "request_id": "req_abc123"
  }
}
```

### Best Practices
1. **Implement exponential backoff** for 429 and 5xx errors
2. **Use idempotency keys** for POST requests to prevent duplicate resource creation
3. **Store webhook event_ids** to handle duplicate deliveries
4. **Monitor rate limit headers** to adjust request frequency proactively
5. **Use sandbox** for all development and testing before going to production
6. **Restrict API key scopes** to the minimum needed for each integration
7. **Whitelist IPs** if possible (configure in API key settings)
8. **Rotate API keys** at least annually; more frequently for production keys
9. **Log all API interactions** for debugging and audit purposes
10. **Subscribe to the ShopStream API changelog** (api.shopstream.com/changelog) for breaking changes

## API Versioning
- API version is specified via the `X-API-Version` header or in the URL path
- Current stable version: `2025-01-15`
- Deprecated versions are supported for 12 months after deprecation notice
- Breaking changes are never introduced without a new version
- Webhook payloads are versioned per webhook subscription (set at creation time)
