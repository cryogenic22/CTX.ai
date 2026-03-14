# Inventory Management Guide

## Overview

The inventory management system tracks product stock levels across all warehouses on the ShopStream platform. Accurate inventory is critical for preventing overselling, optimizing fulfillment, and maintaining customer trust. This document covers the inventory data model, synchronization processes, warehouse operations, and alert mechanisms.

## Inventory Data Model

Inventory is tracked at the variant-warehouse level. Each ProductVariant has a separate Inventory record for each Warehouse where it is stocked. The key quantity fields are:

- **available_quantity**: Units available for sale. Displayed to customers on the storefront.
- **reserved_quantity**: Units reserved for confirmed orders not yet shipped.
- **incoming_quantity**: Units expected from supplier purchase orders.
- **damaged_quantity**: Units marked as unsellable due to damage.

The total physical stock at a warehouse equals: available_quantity + reserved_quantity + damaged_quantity.

The sellable stock displayed to customers equals: available_quantity (summed across all active warehouses for the variant).

## Inventory Lifecycle

### New Stock Arrival
1. Merchant creates a purchase order (outside ShopStream, in their own procurement system)
2. Merchant updates incoming_quantity via API or Merchant Portal
3. When stock arrives at the warehouse, the receiving process is initiated
4. Quality inspection: items are checked for damage and correctness
5. Passed items: incoming_quantity decremented, available_quantity incremented
6. Failed items: incoming_quantity decremented, damaged_quantity incremented
7. Bin location is assigned (or existing bin location is used)
8. Inventory record version is incremented (optimistic locking)

### Order Reservation
1. Customer places order, payment is authorized
2. Order transitions to CONFIRMED
3. Inventory service receives event: reserve stock
4. For each order line: available_quantity decremented, reserved_quantity incremented
5. If multiple warehouses have stock, the allocation algorithm selects the warehouse:
   - Priority 1: Warehouse nearest to the shipping address (haversine distance)
   - Priority 2: Warehouse with the highest priority score
   - Priority 3: Warehouse with the most available stock (to avoid fragmented inventory)
6. If available_quantity is insufficient: order creation fails, customer is notified

### Shipment Creation
1. Merchant picks and packs items
2. Shipment record is created
3. For each item in the shipment: reserved_quantity decremented
4. Inventory record version is incremented

### Return Restock
1. ReturnRequest is completed, inspection passes
2. If restock_inventory = true: available_quantity incremented
3. If inspection fails (damaged): damaged_quantity incremented
4. Bin location is reassigned if needed

## Multi-Warehouse Fulfillment

### Warehouse Selection Algorithm
When a customer places an order, the fulfillment optimizer determines which warehouse(s) should fulfill each line item:

```
For each order_line:
  1. Find all warehouses with available_quantity >= line.quantity for the variant
  2. Filter to warehouses that are active and belong to the merchant
  3. Score each warehouse:
     distance_score = 1 / (haversine(warehouse.lat, warehouse.lon, shipping.lat, shipping.lon) + 1)
     priority_score = 1 / warehouse.priority
     stock_score = warehouse.available_quantity / 1000
     total_score = 0.6 * distance_score + 0.3 * priority_score + 0.1 * stock_score
  4. Select warehouse with highest total_score
  5. If no single warehouse has sufficient stock, split across warehouses (split fulfillment)
```

### Split Fulfillment
- Split orders result in multiple Shipment records for the same order
- The customer is notified about split shipping with separate tracking numbers
- Shipping cost is calculated per shipment; the customer is charged the total
- The order status transitions through PARTIALLY_SHIPPED to SHIPPED

### ShopStream Fulfillment Network (SFN)
- SFN warehouses are pre-positioned across 6 US locations and 3 EU locations
- Merchants pre-ship inventory to SFN warehouses
- SFN offers same-day processing for orders confirmed before the warehouse shipping_cutoff_time
- SFN storage costs: $0.75 per cubic foot per month
- SFN fulfillment costs: $3.50 per order + $0.50/lb after the first pound
- SFN warehouses have warehouse_type = SFN_FACILITY

## Inventory Synchronization

### Real-Time Sync (Storefront)
- When available_quantity changes (reservation, restock, sync), the updated count is pushed to the storefront via WebSocket
- The storefront displays "In Stock", "Low Stock" (<=5 units), or "Out of Stock" (0 units)
- "Low Stock" threshold can be customized by the merchant per product
- Stock level sync latency target: <500ms from database update to storefront display

### Data Warehouse Sync (Daily)
- A daily snapshot of all inventory records is exported to Snowflake at 00:00 UTC
- Historical snapshots enable trend analysis: stock velocity, stockout frequency, overstock detection
- dbt models transform raw snapshots into analytics-ready tables
- Retention: 3 years of daily snapshots

### External System Sync (Merchant ERP/WMS)
- Merchants can sync inventory from their ERP or WMS via:
  - **Push (API)**: Merchant's system calls ShopStream Inventory API to update quantities
  - **Pull (webhook)**: ShopStream sends inventory.updated webhook on every change
  - **Batch (CSV)**: Merchant uploads CSV with SKU-warehouse-quantity mappings
- Conflict resolution: ShopStream is the source of truth for reserved_quantity; merchant is the source for available_quantity during sync
- Sync frequency recommendation: at least every 15 minutes for high-volume merchants

## Physical Count Reconciliation

### Weekly Count Process
1. Warehouse staff performs physical count of selected bins (cycle counting)
2. Counts are entered into the WMS (Warehouse Management System)
3. WMS sends counts to ShopStream via inventory reconciliation API
4. ShopStream compares physical count to system count:
   - last_counted_at is updated
   - last_counted_quantity is recorded
   - count_discrepancy is calculated (physical - system)
5. Discrepancies within 2% of system count: auto-adjusted, logged as WARNING
6. Discrepancies exceeding 2%: flagged for investigation, not auto-adjusted

### Full Physical Inventory
- Conducted annually (or semi-annually for high-volume warehouses)
- All SKUs in the warehouse are counted
- Significant discrepancies (>5%) trigger audit by the operations team
- Results are reported to the merchant and the ShopStream data platform team

### Discrepancy Causes
- **Shrinkage**: Theft, damage not recorded, items lost in warehouse
- **Receiving errors**: Items received but not properly scanned into inventory
- **Shipping errors**: Wrong item picked, quantity mismatch
- **System errors**: Race conditions during high-traffic periods
- **Return processing**: Returned items not properly restocked

## Inventory Alerts

### Low Stock Alert
- Triggered when available_quantity <= reorder_threshold for a variant-warehouse combination
- Notification sent to merchant via email and webhook (inventory.low_stock event)
- Alert includes: SKU, product name, warehouse, current quantity, reorder threshold, suggested reorder quantity

### Stockout Alert
- Triggered when available_quantity reaches 0 for a variant across ALL warehouses
- The product variant is automatically hidden from the storefront (or shown as "Out of Stock")
- Merchant is notified with urgency flagging
- If the variant is in active carts, those customers receive a back-in-stock notification when restocked

### Overstock Alert
- Triggered when available_quantity > max_quantity for a variant-warehouse combination
- Indicates potential data entry error or receiving issue
- Logged as WARNING; merchant is notified

### Stale Inventory Alert
- Triggered when available_quantity > 0 but no orders placed for the variant in 90 days
- Helps merchants identify dead stock for markdowns or liquidation
- Generated weekly in the analytics pipeline

## Inventory API

### Endpoints
- `GET /v1/inventory?variant_id={id}` — Get inventory levels across all warehouses
- `GET /v1/inventory?warehouse_id={id}` — Get all inventory at a warehouse
- `PUT /v1/inventory/{inventory_id}` — Update inventory quantities (requires inventory:write scope)
- `POST /v1/inventory/bulk` — Bulk update inventory from CSV or JSON
- `POST /v1/inventory/reconcile` — Submit physical count for reconciliation

### Rate Limits
- Inventory read: 300 requests/minute (shared with catalog reads)
- Inventory write: 60 requests/minute
- Bulk updates: 10 requests/minute, max 1000 records per request

### Concurrency Control
- All inventory writes use optimistic locking via the version field
- Include `If-Match: {version}` header in update requests
- If version mismatch: HTTP 409 Conflict returned; client must re-read and retry
- This prevents lost updates from concurrent modifications

## Monitoring and Dashboards

### Real-Time Metrics
- Total stockouts across the platform (target: <1% of active SKUs)
- Average inventory turn rate by category
- Order cancellation rate due to inventory issues
- Inventory sync latency (target: <500ms)

### Weekly Reports
- Top 20 stockout SKUs (by lost revenue impact)
- Inventory coverage analysis (days of supply remaining by category)
- Physical count discrepancy summary
- Dead stock identification (>90 days without sale)
