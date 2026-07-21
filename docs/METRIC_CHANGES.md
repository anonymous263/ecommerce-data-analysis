# Metric Changes

> Append-only log of changes to any metric defined in [METRICS_DEFINITION.md](METRICS_DEFINITION.md).
> Each entry: date, metric, old formula, new formula, reason. Newest first. (Per METRICS_DEFINITION §L.)

---

## 2026-07-21 — Customer shipping charge added to the revenue/profit base (Approach A)

- **Metrics:** A-series Revenue (profit base), B-series Contribution Profit & Profit Margin, and every roll-up that reads `mart_order_profit.revenue_usd` / `contribution_profit_usd`.
- **Old formula:** `contribution_profit = net_product_revenue − cogs − design_fee − payment_fee`, where the revenue base was **product line revenue only**; customer shipping (`fact_order.shipping_charged_usd`) was excluded from revenue and loaded "for reconciliation only".
- **New formula:** `contribution_profit = net_revenue − cogs − design_fee − payment_fee`, where `net_revenue = (product_revenue + customer_shipping) − effective_refund` and `gross_revenue = gross_product_revenue + shipping_charged`. `effective_refund = LEAST(refunds, gross_revenue)` — the cap now sits on the order-total base, matching Woo's shipping-inclusive full-order refunds.
- **Effect on live FOS data (cost-covered revenue orders):** contribution profit **$47,536 → $87,138** (+$39,602 = customer shipping net of refunded shipping; gross shipping $39,938). Net revenue base ~$118,280 → **$157,883**. Per-order spot check matches hand calc: order 74030 $4.77 → **$12.86**, order 76100 $7.58 → **$15.65** (each up by its shipping charge). COGS unchanged ($61,062).
- **Reason:** The old base was **asymmetric**. `cogs_usd` (CSV column U) is the *all-in* per-order fulfilment cost — it already includes what the supplier charged the store for shipping. The store also charges the customer for shipping and receives that money. Subtracting the shipping-inclusive COGS while excluding the shipping the customer paid understated every order's profit by exactly its shipping charge. Adding shipping to the base also makes revenue and refunds like-for-like (both order-total), so the refund cap almost never binds. External corroboration: the owner's own CSV `Revenue` is a gross order value ≈ product + shipping (`recon_csv_vs_dbt_revenue.delta_vs_gross_usd` ≈ 0).
- **Conservation re-verified:** shipping is allocated to lines in `mart_product_profit` by the same revenue share as the cost terms (new `line_shipping_usd`). `SUM(line_profit_usd) = SUM(contribution_profit_usd) = $87,138.04` (diff < 1e-4).
- **Files touched:** `dbt/models/marts/core/mart_order_profit.sql`, `mart_product_profit.sql`, `mart_customer_summary.sql`, `mart_country_profit.sql` (comment), `dbt/models/schema.yml`, `dbt/models/marts/reconciliation/recon_csv_vs_dbt_revenue.sql` + `recon_csv_vs_dbt_profit.sql` (comments), `CLAUDE.md` (domain rules #1/#2/#4/#6), `docs/DATA_MODEL.md` (§4.1–4.3), `docs/METRICS_DEFINITION.md` (§A/§B), `powerbi/CAPSTONE_BUILD_GUIDE.md` (profit/margin DAX).
- **Unchanged:** item-grain `fact_order_item.line_revenue_usd` stays product-only (CLAUDE.md rule #1 — the raw revenue column is never mutated); cost/payment-fee/refund coverage gates (order counts, independent of the revenue base).
- **Verification:** `dbt build --select mart_order_profit+` → PASS=33 WARN=0 ERROR=0; aggregate, line↔order conservation, and per-order checks run against real FOS data.

---

## 2026-07-16 — H4 Payment Fee Coverage % rebased to revenue-order basis

- **Metric:** H4 Payment Fee Coverage % (and the §J/§K payment-fee gating chip that reads it).
- **Old formula:** `COUNT(fact_order WHERE payment_fee_usd IS NOT NULL) / COUNT(fact_order)` — over **all** orders.
- **New formula:** `COUNT(revenue orders WHERE payment_fee_usd IS NOT NULL) / COUNT(revenue orders)`, where a *revenue order* has ≥1 `is_revenue_status` line — the **same denominator basis as H1 Cost Coverage** (established in commit `727055c`). The all-orders figure is retained as the informational column `all_order_coverage_pct`.
- **Effect on live FOS data:** coverage reads **98.03%** (3,740 / 3,815 revenue orders) instead of **79.50%** (3,782 / 4,757 all orders). Tier flips from `< 80%` (chip active) to `≥ 80%` (chip off).
- **Reason:** The all-orders denominator counted **900 failed/cancelled/pending orders** that never settled a payment — so no PayPal/Stripe gateway fee was ever charged and their `payment_fee_usd` is correctly NULL. Counting those as "uncovered" understated coverage and falsely tripped the "estimated payment fee" chip. Profit (and therefore the fee gate) is only defined for revenue orders, so the denominator must match — exactly the reasoning behind the H1 cost-coverage rebasing. The genuine capture gap is only **75 revenue orders** where Woo's payload lacked a parseable plugin fee (of which the CSV `Fee` fallback backfills ~70 in `mart_order_profit`).
- **Files touched:** `dbt/models/marts/reconciliation/recon_payment_fee_coverage.sql`, `dbt/tests/singular/assert_payment_fee_coverage_at_least_80.sql`, `docs/METRICS_DEFINITION.md` (§H4, §J), `docs/WOO_PAYLOAD_AUDIT.md` (§6 coverage note), `docs/DASHBOARD_SPEC.md` (§K), `powerbi/measures/dax_measures.txt`, `powerbi/BUILD_GUIDE.md`, `powerbi/VERIFY_5_orders.md`.
- **Verification:** `dbt build --select recon_payment_fee_coverage assert_payment_fee_coverage_at_least_80` → PASS=2 WARN=0 ERROR=0 (the test no longer warns). The raw 79.5% plugin-capture rate over all orders remains documented in `WOO_PAYLOAD_AUDIT.md` as the true source-capture fact.
