# Order Lifecycle Management

## Overview

This document describes the complete lifecycle of an order on the ShopStream platform, from cart conversion through delivery, returns, and archival. Understanding the order lifecycle is essential for engineering, customer service, and operations teams. The order state machine is the backbone of the platform and drives downstream processes including payment capture, inventory management, fulfillment, settlement, and analytics.

## Order State Machine

The order follows a defined state machine with the following statuses:

```
PENDING → CONFIRMED → PROCESSING → PARTIALLY_SHIPPED → SHIPPED → DELIVERED
                                                                      ↓
PENDING → CANCELLED                                     RETURN_REQUESTED → RETURNED
CONFIRMED → CANCELLED
PENDING → FAILED
```

### Status Definitions

**PENDING**: Order has been placed (checkout completed) but payment has not yet been confirmed. The payment gateway has received an authorization request. Inventory is soft-reserved (not yet decremented). Orders remain in PENDING for a maximum of 30 minutes; if payment authorization is not confirmed within this window, the order transitions to FAILED and inventory reservations are released.

**CONFIRMED**: Payment has been authorized (not yet captured). Inventory is now hard-reserved (available_quantity decremented, reserved_quantity incremented). The merchant and customer both receive confirmation notifications. The merchant has a configurable window (default: 3 business days) to ship the order before it is flagged as overdue.

**PROCESSING**: The merchant has acknowledged the order and is preparing it for shipment. This is an optional status used by merchants with complex fulfillment processes (e.g., custom or made-to-order items). Not all orders pass through PROCESSING; some go directly from CONFIRMED to SHIPPED.

**PARTIALLY_SHIPPED**: At least one but not all shipments for the order have been dispatched. This occurs when an order is split across multiple warehouses or when a merchant ships items as they become available. The order remains in this status until all shipments are dispatched.

**SHIPPED**: All items in the order have been dispatched. Payment is captured (moved from AUTHORIZED to CAPTURED in the Payment entity) at this point. The customer receives a shipping confirmation email with tracking information for all shipments.

**DELIVERED**: All shipments have been confirmed as delivered (via carrier tracking webhook or customer confirmation). This is a terminal status for successful orders. The order becomes eligible for review submission 24 hours after delivery.

**CANCELLED**: The order has been cancelled before shipment. Cancellation can be initiated by the customer (if the order is still in PENDING or CONFIRMED status), the merchant (for any reason before shipping), or the system (payment failure, fraud detection). When cancelled, inventory reservations are released and if payment was authorized, it is voided. The cancellation_reason field must be populated.

**RETURN_REQUESTED**: A return has been initiated against this delivered order. The order status changes from DELIVERED to RETURN_REQUESTED when a ReturnRequest is created. If only some items are being returned, the order still moves to RETURN_REQUESTED.

**RETURNED**: All items in the return request have been received and processed. The refund has been issued. If the return was partial, the order still shows as RETURNED in the order table, but the financial records reflect the partial refund amount.

**FAILED**: Payment authorization failed or timed out. This is a terminal status. The customer is notified and can retry the purchase. Cart items remain in the customer's cart for convenience.

## Order Creation (Checkout Flow)

The order creation process involves multiple services and follows this sequence:

1. **Cart Validation** (cart-service)
   - Verify all items are still in stock (real-time inventory check)
   - Verify product availability (active status, not suspended)
   - Verify prices have not changed since the cart was populated
   - Apply and validate coupon code if provided
   - Calculate line-level discounts from active promotions

2. **Address Validation** (identity-service)
   - Verify shipping and billing addresses exist and belong to the customer
   - Address verification via SmartyStreets API (US addresses)
   - Validate shipping address is serviceable by the merchant's shipping zones

3. **Tax Calculation** (tax-service)
   - Determine applicable tax rules based on shipping address jurisdiction
   - Calculate line-level tax amounts based on product tax categories
   - For US addresses, real-time rate lookup via Avalara integration
   - Apply tax exemptions if applicable (B2B with valid tax ID)

4. **Shipping Calculation** (shipping-service)
   - Determine optimal warehouse(s) for fulfillment based on proximity and inventory
   - Calculate shipping cost based on carrier, service level, weight, and destination
   - Apply free shipping if order meets threshold or merchant has free shipping enabled

5. **Order Creation** (order-management-service)
   - Generate order_id (UUID v4) and order_number (SS-YYYYMMDD-XXXXXX)
   - Create Order record with status PENDING
   - Create OrderLine records for each item
   - Record the applied coupon and increment its usage_count
   - Record ip_address and user_agent for fraud detection

6. **Payment Authorization** (payment-service)
   - Create Payment record with status PENDING
   - Submit authorization request to payment gateway (Stripe or Adyen)
   - If fraud_score > 80: queue for manual review
   - If fraud_score > 95: auto-decline and transition order to FAILED
   - If authorization succeeds: Payment → AUTHORIZED, Order → CONFIRMED
   - If authorization fails: Payment → FAILED, Order → FAILED

7. **Inventory Reservation** (inventory-service)
   - On CONFIRMED: decrement available_quantity, increment reserved_quantity
   - Uses optimistic locking to prevent overselling
   - If inventory has changed since cart check: roll back order, notify customer

8. **Notification** (notification-service)
   - Send order confirmation email to customer
   - Send new order notification to merchant (email + webhook)
   - If payment failed, send failure notification with retry instructions

## Marketplace Orders (Multi-Merchant)

For orders containing items from multiple merchants:

1. A parent order is created with order_type MARKETPLACE
2. Sub-orders are created for each merchant (each with their own order_id)
3. Sub-orders reference the parent via parent_order_id
4. Each sub-order has its own payment, fulfillment, and settlement lifecycle
5. The customer sees the parent order in their order history, with shipments grouped by merchant
6. Payment is a single charge on the parent order; funds are split to sub-orders during settlement

## Cancellation Rules

### Customer-Initiated Cancellation
- Allowed while order is in PENDING or CONFIRMED status
- Not allowed once the order is in PROCESSING, SHIPPED, or DELIVERED status
- For PROCESSING orders, customer can request cancellation but merchant must approve
- Cancellation of marketplace parent orders cancels all sub-orders
- Inventory reservations are released immediately on cancellation

### Merchant-Initiated Cancellation
- Allowed at any status before DELIVERED
- Must provide a cancellation_reason
- Triggers automatic full refund to the customer
- Repeated merchant cancellations (>5% of orders) trigger performance review
- Merchant cancellations are tracked separately from customer cancellations in analytics

### System-Initiated Cancellation
- Payment authorization timeout (30 minutes)
- Fraud detection (fraud_score > 95)
- Inventory no longer available (race condition in high-traffic scenarios)
- Merchant account suspended during order processing

## Fulfillment Process

### Standard Fulfillment
1. Merchant views new orders in Merchant Portal or via webhook
2. Merchant picks and packs items at the designated warehouse
3. Merchant generates shipping label (via ShopStream label service or their own carrier account)
4. Merchant marks items as fulfilled, creating a Shipment record
5. Shipment triggers: inventory reserved_quantity decrement, carrier tracking webhook registration

### Split Fulfillment
- When items are in different warehouses, the system creates separate fulfillment tasks
- Each warehouse fulfills their portion independently
- Multiple Shipment records are created for the same order
- Order status moves to PARTIALLY_SHIPPED when the first shipment is dispatched
- Order status moves to SHIPPED when the last shipment is dispatched

### SFN (ShopStream Fulfillment Network)
- Merchants using SFN pre-ship inventory to ShopStream warehouses
- ShopStream handles picking, packing, and shipping
- SFN orders have faster fulfillment (same-day processing for orders before cutoff)
- SFN fees are recorded as PlatformFee records

## Edge Cases and Known Issues

### Overselling Prevention
- The inventory service uses PostgreSQL advisory locks during checkout
- In extreme traffic (>1000 concurrent checkouts for the same variant), there is a known race condition window of ~50ms
- Mitigation: a background reconciliation job runs every 5 minutes to catch and cancel oversold orders
- When an oversold order is detected, the system auto-cancels the most recent order(s)

### Payment Capture Timing
- Payment is authorized at checkout but captured (charged) at shipment time
- Authorization holds expire after 7 days for most card issuers
- For orders not shipped within 7 days, a re-authorization is attempted
- If re-authorization fails, the merchant is notified and must contact the customer

### Partial Delivery Issues
- If a carrier reports partial delivery (some items missing), the order remains in SHIPPED status
- The customer must initiate a return/refund for undelivered items
- The merchant is responsible for filing a carrier claim

### Order Amendments After Confirmation
- Order amounts cannot be changed after CONFIRMED status
- Address changes are allowed before PROCESSING if the merchant hasn't begun fulfillment
- Product substitutions are not supported; the customer must cancel and re-order
- Adding items to an existing order is not supported

## SLA and Monitoring

### Fulfillment SLA
- Standard merchants: ship within 3 business days of CONFIRMED
- Premium merchants: ship within 2 business days
- SFN orders: ship same business day if confirmed before warehouse cutoff time
- Orders not shipped within SLA: automated alert to merchant + account manager notification

### Delivery SLA (carrier-dependent)
- Economy: 5-8 business days
- Standard: 3-5 business days
- Express: 1-2 business days
- Overnight: next business day
- Same-Day: delivery by 9 PM on the order date (limited markets)

### Monitoring Dashboards
- Real-time order funnel (cart → checkout → payment → confirmation → fulfillment → delivery)
- Fulfillment SLA compliance by merchant (target: 95%)
- Cancellation and failure rates by cause
- Payment authorization success rates by gateway and card type
- Average delivery time by carrier and service level
