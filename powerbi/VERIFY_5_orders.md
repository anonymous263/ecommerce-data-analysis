# Phase 4 Verification — Hand-Calc Ground Truth

> ⚠️ **Aggregate cards below are FROZEN pre-cleanup (2026-07-21)** — superseded by the
> capstone model. Current canonical aggregates: `CAPSTONE_BUILD_GUIDE.md` §Kiểm chứng /
> `docs/METRIC_CHANGES.md` (2026-07-23). The **5 sample orders remain exactly valid**
> (re-verified byte-identical against the warehouse on 2026-07-23) — keep using them
> for hand-calc checks.
>
> Pulled live from the warehouse (FOS, whole dataset). Revenue/profit basis updated
> **2026-07-21 for Approach A** — the customer shipping charge is now revenue in the
> profit base (see `docs/METRIC_CHANGES.md`). Use this to satisfy TASKS.md L225
> ("Hand-calc 5 orders end-to-end → match cards"): after building the `.pbix`, filter
> to each `woo_order_id` below and confirm the card values match. Every profit figure
> here reconciles: `contribution_profit_usd == net_revenue − cogs − design_fee −
> payment_fee`, where `net_revenue = (product_revenue + shipping_charged) − effective_refund`.

## Aggregate cards (no filter — Executive Overview + Data Quality)

| Card | Measure | Expected |
|---|---|---|
| Revenue (gross, product) | `[Revenue]` (§A1) | **$119,376.98** |
| Net Revenue (product, reporting) | `[Net Revenue]` (§A2) | **$117,911.47** |
| Orders | `[Orders]` (§A3, status ∈ processing/completed/on-hold) | **3,789** |
| AOV | `[AOV]` (§A5) | **$31.51** |
| Shipping Charged to Customer | `[Shipping Charged to Customer]` (§A7, revenue-side) | **$50,648.98** |
| **Profit Base Net Revenue** | `[Profit Base Net Revenue]` (§B5, product + shipping − refund) | **$157,882.62** |
| Refunded Order Count | `[Refunded Order Count]` (§C1) | **34** |
| Refund Amount | `[Refund Amount]` (§C2) | **$1,465.51** |
| Contribution Profit | `[Contribution Profit]` (§B5) | **$87,138.04** |
| Profit Margin | `[Profit Margin]` (§B6, ÷ Profit Base) | **55.19%** |
| **Cost Coverage %** | `[Cost Coverage %]` (§H1) | **98.79% → GREEN** (profit shown, no partial chip) |
| **Payment Fee Coverage %** | `[Payment Fee Coverage %]` (§H4, revenue-order basis) | **98.03% → ≥80%, payment-fee chip OFF** (all-orders 79.50% is informational) |

## 5 sample orders (spread: normal profit, near-breakeven, fully-refunded ×2, refunded-with-COGS)

All money USD. `gross_rev = product_revenue + shipping_charged` (Approach A).
`profit_recompute = net_rev − cogs − design − pay_fee` (must equal the mart's `contribution_profit_usd`).

| woo_order_id | site | country | prod_rev | ship | gross_rev | refunds | net_rev | cogs | design | pay_fee | pay_fee_source | **profit** | note |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **74030** | FOS | US | 24.82 | 8.09 | 32.91 | 0.00 | 32.91 | 15.21 | 3.04 | 1.80 | missing→CSV | **12.86** | normal profitable order |
| **74062** | FOS | US | 36.4283 | 11.2814 | 47.7097 | 0.00 | 47.7097 | 20.84 | 6.09 | 2.3571 | missing→CSV | **18.4226** | normal profitable order |
| **73874** | FOS | US | 6.12 | 7.95 | 14.07 | 0.00 | 14.07 | 14.07 | 0.00 | 0.92 | missing→CSV | **−0.92** | shipping revenue offsets high COGS → only the payment fee is a loss |
| **80673** | FOS | US | 100.10 | 21.29 | 121.39 | 121.39 | 0.00 | 0.00 | 0.00 | 5.64 | plugin_parser | **−5.64** | fully refunded (refund = product+ship) → net 0; payment fee is a sunk loss |
| **137227** | FOS | US | 48.08 | 12.12 | 60.20 | 62.60 | 0.00 | 21.98 | 1.38 | 2.305 | plugin_parser | **−25.665** | refund > gross → net 0 (capped), but item **was** produced → COGS loss |

### What each edge case proves
- **74030 / 74062** — ordinary orders reconcile exactly; profit now includes the shipping the customer paid (net = product + shipping, no refund).
- **73874** — product revenue ($6.12) is below COGS ($14.07), but the customer also paid $7.95 shipping; counting that (Approach A) turns a phantom −$8.87 "loss" into a near-breakeven −$0.92 (just the payment fee). This is exactly the asymmetry the old model got wrong.
- **80673** — refund ($121.39) equals gross (product $100.10 + shipping $21.29); `effective_refund` caps at gross so net revenue floors at 0 (the sale is reversed, not inverted). Only the payment fee remains as a loss.
- **137227** — refund ($62.60) exceeds gross ($60.20); same cap → net 0. This order had real COGS ($21.98): a fully-refunded order still carries its production cost as a loss, because the item was fulfilled before the money was returned.

> Cross-checks: `[Shipping Charged to Customer]` is **revenue-side** — it is added to the
> revenue base (Approach A) and is **never** subtracted as a cost (COGS already includes
> the supplier fulfilment/shipping fee). `[Contribution Profit]` on a single-order filter
> must equal the **profit** column above.
