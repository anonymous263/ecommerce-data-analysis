# Metric Changes

> Append-only log of changes to any metric defined in [METRICS_DEFINITION.md](METRICS_DEFINITION.md).
> Each entry: date, metric, old formula, new formula, reason. Newest first. (Per METRICS_DEFINITION §L.)

---

## 2026-07-23 — Data cleanup (no formula changes): reference values re-baselined

- **Metric:** none redefined — every formula is unchanged. This entry re-baselines the **live FOS reference values** quoted across docs/measure descriptions after the 2026-07-22→23 Woo↔CSV reconciliation (sheet + Woo status/total/currency/shipping fixes; 50 flagged orders re-fetched; 37 hard-deleted Woo orders excluded by design; off-platform `_n`-suffixed sheet codes now skipped by the CSV loader).
- **New canonical (all-time FOS):** Paid Orders **3,813** (completed 3,698 + processing 78 + refunded 37) · Contribution Profit **$86,670.64** · Profit Base Net Revenue **$157,614.83** · Product Revenue **$119,261.71** · COGS **$61,256.69** · Design Fee **$2,556.39** · Payment Fee **$7,131.11** (fact_order-side reads $7,069.77, delta $61.34) · Total Cost **$70,944.19** · AOV **$31.28** · Margin **55.0%** · Refunded Orders **37** (raw refunds $1,592.02, capped $1,582.49) · Cancelled **499** · Failed **437** · Cost Coverage **98.92% GREEN** · Fee Coverage **98.03%**.
- **Superseded figures** you may still see in older entries below (correct as of their dates): $87,138.04 profit, 3,812/3,815 paid orders, $157,882.62 base, 98.79% coverage, 34 refunds, 497 cancelled. The 2026-07-22 country cross-check figures (US $53,140.81 / UK $27,750.51 / DE $7,496.61) do not match any current partition — current billing-country split is US $36,476.43 / GB $21,060.08 / DE $5,765.55 (mart_country_profit, sums exactly to $86,670.64).
- **Files touched:** `docs/METRICS_DEFINITION.md`, `docs/DATA_MODEL.md`, `powerbi/CAPSTONE_BUILD_GUIDE.md`, `powerbi/ecommerce_analytics.SemanticModel/.../_Measures.tmdl` (descriptions only — no DAX expression changed), legacy `powerbi/BUILD_GUIDE.md` / `VERIFY_5_orders.md` / `measures/dax_measures.txt` marked as frozen pre-cleanup.
- **Verification:** dbt PASS=201 WARN=0; mart↔item population 3,813 = 3,813; SUM(line_profit_usd) = $86,670.64 = SUM(contribution_profit_usd); the 5 hand-calc orders in VERIFY_5_orders.md are byte-identical pre/post cleanup.

## 2026-07-22 — Capstone measure set merged into the shared model; five metrics rebased

- **Context:** the capstone operational dashboard and the ecom MVP now share one semantic model (`ecommerce_analytics`). 40 capstone measures and 3 calculated columns were added under `Capstone\*` display folders. Five measures existed in both sets under the **same name with different formulas**; per owner decision the capstone definition wins.
- **Metrics rebased:**
  | Metric | Old (ecom) | New (capstone) | FOS value |
  |---|---|---|---|
  | §A5 AOV | `Revenue / Orders` (3,789) | `Revenue / Paid Orders` (3,812) | $31.51 → **$31.32** |
  | §C3 Refund Rate | (refunded ∪ cancelled) / Eligible | Refunded / Paid Orders | → **0.9%** |
  | §C4 Cancellation Rate | ÷ Eligible Orders | ÷ Order Attempts | → **10.4%** |
  | §I1 Distinct Customers | known-email only | whole base | 4,263 → **4,266** |
  | §I3 Orders per Customer | `[Orders]/[Distinct Customers]` | `SUM(total_orders)/customers` | 0.89 → **1.12** |
- **Knock-on fixes applied in the same pass:** `[AOV (min 10 orders)]` and `[Refund Rate (min 10 orders)]` guarded on populations their parent measures no longer used (`[Orders]` and `[Eligible Orders]`); both rebased to `[Paid Orders]`. Without this the guard would have counted 3,789 while the value divided by 3,812.
- **Reason per metric:** AOV/Refund/Cancellation align every ratio to one denominator so the operations funnel is additive (Paid 80.1% + Failed 9.2% + Cancelled 10.4% ≈ 100%). §I3's old form mixed a filter-context numerator with a lifetime denominator and returned 0.89 — below 1.0, impossible for a lifetime average. §I1 widening is the one that *loses* information (guest checkouts are no longer excluded); it is accepted because the capstone Customers page reports on the whole base, and the guest-checkout caveat already on the dashboard now matters more, not less.
- **Retained, not deleted:** `[Orders]`, `[Eligible Orders]`, `[Refunded or Cancelled Orders]`, `[Repeat Customer Share]`, `[Open Order Backlog]`, `[Shipping Charged to Customer]`, `[Refunded Order Count]` all still exist — the old combined refund rate can be rebuilt from them at any time.
- **Known limitation (not fixed):** `[Refund Rate]` reads `fact_refund`/`fact_order`, neither of which has a `dim_country` relationship, so on a country visual it returns the all-store rate. Documented in the measure description and in `dax_measures.txt`; a country-aware refund measure would need a new mart.
- **Also added:** calculated columns `Days Since Last Order`, `Recency Segment`, `CLV Bucket` on `mart_customer_summary`. The recency anchor uses `CALCULATE(MAX(last_order_date), ALL(...))` rather than the capstone guide's hardcoded `DATE(2026,7,14)`, so it self-corrects on refresh. Note `dim_date` runs to 2030-12-31, so `MAX(dim_date[date_day])` must never be used as the anchor.
- **Verification:** every capstone KPI checked live via DAX against the guide — Revenue $119,376.98, Paid Orders 3,812, Total Cost $70,744.58, Contribution Profit $87,138.04, margin 55.19%, reconciliation delta −2.9e-11. Grand-total bug confirmed fixed: `[Product Profit]` and `[Country Profit]` now vary per row where `[Contribution Profit]` still returns $87,138.04 for every row (by design — it has no product/country relationship). Country figures cross-validated against independent SQL: US $53,140.81 / 54.6%, UK $27,750.51 / 56.3%, DE $7,496.61 / 58.5%.
- **Files touched:** `powerbi/measures/dax_measures.txt`, `docs/METRICS_DEFINITION.md` (§A5, §C3, §C4, §I1, §I3), and the live model (`_Measures.tmdl` will pick up all 40 additions on the next Power BI Desktop save).

---

## 2026-07-22 — B2 Payment Fee rebased to the mart column that profit actually subtracts

- **Metric:** B2 Payment Fee (DAX `[Payment Fee]`), and any cost-breakdown visual that sums COGS + Design Fee + Payment Fee.
- **Old formula:** `SUM(fact_order.payment_fee_usd)` — as literally specified in §B2.
- **New formula:** `SUM(mart_order_profit.payment_fee_usd)`, i.e. `coalesce(fact_order.payment_fee_usd, fact_order_cost.payment_fee_fallback_usd, 0)`.
- **Effect on live FOS data:** Payment Fee **$7,069.77 → $7,128.11** (+$58.34). Total cost becomes **$70,744.58**, and the breakdown now reconciles exactly: `157,882.62 − 70,744.58 = 87,138.04 = SUM(contribution_profit_usd)`, delta **$0.00**. Contribution profit, margin, COGS and design fee are all unchanged — only the fee line and totals derived from it move.
- **Reason:** `[Contribution Profit]` subtracts the **mart** column, so reading `fact_order` meant the cost breakdown never added up to the profit it was supposed to explain — it fell **$137.72 short** on the same order population. Two independent causes stacked: (a) `fact_order` spans non-revenue orders while the mart is revenue-orders-only, and (b) the mart coalesces the CSV `Fee` fallback for the ~20% of orders where Woo carries no fee (the ~70 backfilled orders noted in the 2026-07-16 entry below), which `fact_order` lacks entirely. Sibling measures §B1 `COGS` and §B3 `Design Fee` already read the mart; `[Payment Fee]` was the only cost term reading a different table. The DAX was **faithful to §B2** — the spec itself was stale, written before the fallback landed, which is why `docs/DATA_MODEL.md` §4.2 already documented the `coalesce` correctly while §B2 did not.
- **Not changed:** `payment_fee_source` still reports **Woo's own** classification (`'missing'` when the fallback supplied the value), so the source mix and the fee value legitimately come from different places — H4 coverage semantics and the §K chip are untouched. Capstone's `[Payment Fee Rate]` keeps its `fact_order` numerator **and** denominator, since it measures the effective processor rate over all order value rather than a P&L line.
- **Files touched:** `docs/METRICS_DEFINITION.md` (§B2), `powerbi/measures/dax_measures.txt`, `powerbi/ecommerce_analytics.SemanticModel/definition/tables/_Measures.tmdl`, `docs/learning/11-dax-measures-giai-thich.md` (B-2).
- **Verification:** reconciliation checked directly against `marts_core.mart_order_profit` on real FOS data — implied profit from the cost breakdown equals `contribution_profit_usd` to $0.00. `pytest` 84 passed.

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
