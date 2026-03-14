# Payment Processing Guide

## Overview

ShopStream processes payments through a multi-gateway architecture designed for reliability, compliance, and global reach. The payment system handles authorization, capture, refunds, and settlement across 22 supported currencies. This document covers the payment processing flow, supported methods, fraud prevention, PCI-DSS compliance, and common troubleshooting procedures.

## Supported Payment Methods

### Credit and Debit Cards
- **Visa** — All markets
- **Mastercard** — All markets
- **American Express** — US, UK, EU, Canada, Australia, Japan
- **Discover** — US only
- **JCB** — Japan, select other markets
- **UnionPay** — China, select other markets
- Card payments are processed through Stripe (primary) with Adyen as failover

### Digital Wallets
- **Apple Pay** — Available on Safari, iOS devices
- **Google Pay** — Available on Chrome, Android devices
- Digital wallet payments use tokenized card credentials; the flow is identical to card payments from the backend perspective

### PayPal
- Available in all markets where PayPal operates
- Processed directly through PayPal's API (not through Stripe/Adyen)
- Supports PayPal balance, linked bank account, and PayPal Credit

### Buy Now, Pay Later (BNPL)
- **Klarna** — US, UK, EU (via Stripe integration)
- **Afterpay** — US, UK, Australia (via Stripe integration)
- BNPL payments are authorized and captured like regular payments; the installment terms are managed by the BNPL provider
- ShopStream receives the full payment upfront; the BNPL provider collects from the customer

### Gift Cards and Store Credit
- ShopStream-issued gift cards (physical and digital)
- Store credit from refunds (when customer opts for store credit instead of original payment method refund)
- Gift cards and store credit can be combined with another payment method for the remaining balance

### Not Supported
- The ShopStream platform does not support cryptocurrency payments. There are no plans to add cryptocurrency support.
- Cash on delivery (COD) is not supported.
- Bank transfers are not supported as a direct payment method for orders (only for merchant settlement payouts).
- Pre-paid debit cards with insufficient balance will be declined; partial authorizations are not supported.

## Payment Processing Flow

### Authorization
1. Customer selects payment method and submits checkout
2. Payment-service creates a Payment record with status PENDING
3. Fraud scoring via Sift Science integration (score 0-100)
4. If fraud_score <= 80: proceed to authorization
5. If fraud_score 80-95: queue for manual fraud review (PENDING_REVIEW)
6. If fraud_score > 95: auto-decline, Payment → FAILED
7. Authorization request sent to primary gateway (Stripe)
8. If Stripe is unavailable (timeout or 5xx error): failover to Adyen
9. 3D Secure (3DS) authentication if required by card issuer or risk rules
10. Authorization response: approved or declined
11. If approved: Payment → AUTHORIZED, hold placed on customer's card
12. If declined: Payment → FAILED, order → FAILED, customer notified

### 3D Secure (3DS) Authentication
- 3DS is mandatory for EU transactions (PSD2 Strong Customer Authentication)
- 3DS is triggered for non-EU transactions when the fraud score is between 50 and 80
- 3DS results: AUTHENTICATED (success), ATTEMPTED (issuer not enrolled but attempted), FAILED (customer failed challenge), NOT_ENROLLED (card not enrolled)
- Failed 3DS does not automatically decline; the authorization may still proceed with a liability shift

### Capture
- Payment capture is triggered when the merchant creates a Shipment (marks order as shipped)
- For digital goods (requires_shipping = false), capture happens immediately after authorization
- Capture request moves Payment from AUTHORIZED to CAPTURED
- If the authorization has expired (>7 days), a re-authorization is attempted before capture
- Failed re-authorization: order is flagged for merchant attention

### Settlement
- Captured payments are settled by the gateway on a rolling basis (typically T+2 for Stripe)
- Payment → SETTLED when funds reach ShopStream's bank account
- Settlement funds are then pooled and distributed to merchants per their settlement schedule
- Settlement calculations include commission deductions, refund deductions, and fee deductions

## Refund Processing

### Refund Types
1. **Full Refund**: Entire order amount returned to customer. Order status → RETURNED.
2. **Partial Refund**: Specific amount or line items refunded. Order remains in current status.
3. **Store Credit**: Refund issued as ShopStream store credit instead of payment method reversal.

### Refund Flow
1. Return is approved (or direct refund is authorized by customer service)
2. Refund record is created with status REQUESTED
3. Refund amount validated: cannot exceed original payment minus prior refunds
4. Refund request sent to the payment gateway
5. Gateway processes reversal to the original payment method
6. Refund → COMPLETED when gateway confirms
7. Refund amount is deducted from the merchant's next settlement

### Refund Timing
- Card refunds: 5-10 business days to appear on customer's statement
- PayPal refunds: 3-5 business days
- Store credit: Available immediately
- Gift card refunds: Refunded to the original gift card or a new card if original is expired

### Refund Windows by Product Category
- Standard products: 30 days from delivery
- Electronics: 30 days from delivery
- Perishable goods: 7 days from delivery
- Digital goods: 14 days from purchase (or 48 hours after first access, whichever is sooner)
- Personalized items: Non-refundable (unless defective)
- ShopStream Plus members: Extended to 90 days for most categories

**Note**: The refund window documented here (30 days for electronics) may differ from the ReturnRequest entity description, which states 14 days for electronics and opened software. The 30-day window applies to unopened electronics returned in original packaging; the 14-day window applies to opened electronics. This distinction is enforced by the return eligibility rules engine.

## Multi-Currency Processing

### Price Display
- Products are listed in the merchant's base currency
- Customer sees prices in their preferred currency (set in profile or auto-detected from geo-IP)
- Currency conversion uses the current ExchangeRate with a 1.5% platform markup
- Converted prices are displayed with a "Prices in {currency} are approximate" disclaimer

### Transaction Currency
- The payment is charged in the customer's selected currency
- The Payment record stores the charged amount and currency
- Exchange rate at the time of payment is locked for the transaction
- Merchant settlement is always in the merchant's configured settlement currency

### Cross-Currency Refunds
- Refunds are processed in the original transaction currency
- The customer receives the exact amount in the currency they were charged
- Exchange rate differences between payment and refund are absorbed by the platform
- Currency conversion fees for cross-currency refunds are recorded as PlatformFee entries

## Fraud Prevention

### Automated Screening (Sift Science)
Every payment authorization triggers a fraud evaluation:
- **Device fingerprinting**: Identifies the customer's device across sessions
- **Behavioral analysis**: Analyzes browsing and purchasing patterns
- **Velocity checks**: Detects rapid-fire purchases from the same device/IP
- **Address verification**: Compares billing address with card issuer records
- **IP geolocation**: Flags transactions where IP country differs from billing country

### Risk Score Actions
| Score Range | Action |
|------------|--------|
| 0-50 | Approved automatically |
| 51-79 | Approved with monitoring flag |
| 80-95 | Queued for manual review (PENDING_REVIEW) |
| 96-100 | Auto-declined |

### Manual Fraud Review
- Performed by the trust & safety team within 4 hours (business hours)
- Reviewer examines: order history, device fingerprint, address match, velocity patterns
- Outcomes: APPROVED (proceed with capture), DECLINED (void authorization, notify customer), ESCALATED (additional investigation needed)

### Chargeback Management
- Chargebacks are received via gateway webhook
- Payment status → DISPUTED
- Automated evidence compilation: order details, delivery proof, customer communication history
- Response deadline: 7 days from chargeback notification
- Chargeback fee ($15) is charged to the merchant regardless of outcome
- Merchants with chargeback rate >1% are flagged for review

## PCI-DSS Compliance

### Scope
- ShopStream is PCI-DSS Level 1 certified (annual on-site audit)
- Raw card numbers never enter ShopStream systems; all card data is tokenized at the browser level via Stripe.js / Adyen Web Components
- The Cardholder Data Environment (CDE) consists solely of the payment-service and its dedicated database
- Network segmentation isolates the CDE from all other services

### Data Storage
- **Never stored**: Full card number (PAN), CVV/CVC, magnetic stripe data
- **Stored (tokenized)**: Gateway token (e.g., pm_xxx), card_last_four, card_brand, card_exp_month, card_exp_year
- **Encryption**: All stored payment data encrypted with AES-256; keys managed by AWS KMS
- **Access**: Payment data access restricted to the payment-service service account; no human access to production payment databases

### Key Rotation
- Encryption keys are rotated annually
- Gateway tokens do not expire (managed by Stripe/Adyen)
- API keys for gateway access are rotated quarterly

## Troubleshooting Common Issues

### "Payment Declined" Errors
1. **Insufficient funds**: Customer should try a different card
2. **Card expired**: Customer should update payment method
3. **Issuer decline**: Customer should contact their bank
4. **CVV mismatch**: Customer should re-enter card details
5. **3DS failure**: Customer should retry; may need to contact bank to whitelist ShopStream

### Authorization Expiry
- Symptom: Merchant cannot capture payment for an old order
- Cause: Authorization expired (>7 days)
- Resolution: System attempts re-authorization automatically. If re-auth fails, merchant must contact customer for a new payment.

### Double Charges
- Symptom: Customer reports being charged twice
- Cause: Usually a display issue; the first charge is the authorization hold, the second is the capture. The hold drops off within 3-5 business days.
- If genuinely double-charged: Identify using idempotency_key; void the duplicate charge.

### Refund Not Appearing
- Timing: Card refunds take 5-10 business days
- Check Refund status: Must be COMPLETED (not PROCESSING)
- Gateway verification: Check gateway_refund_id in the payment gateway dashboard
- If refund is stuck in PROCESSING: Check for gateway errors in the refund failure_reason field
