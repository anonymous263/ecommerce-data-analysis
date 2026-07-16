# Phase 4 Verification — Hand-Calc Ground Truth

> Pulled live from the warehouse (FOS, whole dataset) on 2026-07-16. Use this to satisfy
> TASKS.md L225 ("Hand-calc 5 orders end-to-end → match cards"): after building the `.pbix`,
> filter to each `woo_order_id` below and confirm the card values match. Every profit figure
> here already reconciles: `contribution_profit_usd == net_revenue − cogs − design_fee − payment_fee`.

## Aggregate cards (no filter — Executive Overview + Data Quality)

| Card | Measure | Expected |
|---|---|---|
| Revenue (gross) | `[Revenue]` (§A1) | **$119,376.98** |
| Net Revenue | `[Net Revenue]` (§A2) | **$117,911.47** |
| Orders | `[Orders]` (§A3, status ∈ processing/completed/on-hold) | **3,789** |
| AOV | `[AOV]` (§A5) | **$31.51** |
| Shipping Charged to Customer | `[Shipping Charged to Customer]` (§A7, revenue-side) | **$50,648.98** |
| Refunded Order Count | `[Refunded Order Count]` (§C1) | **34** |
| Refund Amount | `[Refund Amount]` (§C2) | **$1,465.51** |
| Contribution Profit | `[Contribution Profit]` (§B5) | **$47,535.65** |
| Profit Margin | `[Profit Margin]` (§B6) | **40.19%** |
| **Cost Coverage %** | `[Cost Coverage %]` (§H1) | **98.79% → GREEN** (profit shown, no partial chip) |
| **Payment Fee Coverage %** | `[Payment Fee Coverage %]` (§H4) | **79.50% → <80%, payment-fee chip ACTIVE** |

## 5 sample orders (spread: normal profit, loss, fully-refunded ×2, refunded-with-COGS)

All money USD. `profit_recompute = net_rev − cogs − design − pay_fee` (must equal the mart's `contribution_profit_usd`).

| woo_order_id | site | country | gross_rev | refunds | net_rev | cogs | design | pay_fee | pay_fee_source | **profit** | ship_charged | note |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **74030** | FOS | US | 24.82 | 0.00 | 24.82 | 15.21 | 3.04 | 1.80 | missing→CSV | **4.77** | 8.09 | normal profitable order |
| **74062** | FOS | US | 36.4283 | 0.00 | 36.4283 | 20.84 | 6.09 | 2.3571 | missing→CSV | **7.1412** | 11.2814 | normal profitable order |
| **73874** | FOS | US | 6.12 | 0.00 | 6.12 | 14.07 | 0.00 | 0.92 | missing→CSV | **−8.87** | 7.95 | loss: COGS > revenue (real) |
| **80673** | FOS | US | 100.10 | 121.39 | 0.00 | 0.00 | 0.00 | 5.64 | plugin_parser | **−5.64** | 21.29 | fully refunded → net 0; payment fee is a sunk loss |
| **137227** | FOS | US | 48.08 | 62.60 | 0.00 | 21.98 | 1.38 | 2.305 | plugin_parser | **−25.665** | 12.12 | refunded → net 0, but item **was** produced → COGS loss |

### What each edge case proves
- **74030 / 74062** — ordinary orders reconcile exactly (`net = gross`, no refund).
- **73874** — a genuine loss where cost exceeds revenue is shown, not clamped to zero.
- **80673** — refund ($121.39) exceeds gross ($100.10); `effective_refund` is **capped at gross** so net revenue floors at 0 (the sale is reversed, not inverted). Only the payment fee remains as a loss.
- **137227** — same cap, but this order had real COGS ($21.98): a fully-refunded order still carries its production cost as a loss, because the item was fulfilled before the money was returned. This is the locked refund-netting behavior (commit `727055c`).

> Cross-checks: `[Shipping Charged to Customer]` values are **revenue-side** and must **never** appear in any profit formula. `[Contribution Profit]` on a single-order filter must equal the **profit** column above.
