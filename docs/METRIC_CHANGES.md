# Metric Changes

> Append-only log of changes to any metric defined in [METRICS_DEFINITION.md](METRICS_DEFINITION.md).
> Each entry: date, metric, old formula, new formula, reason. Newest first. (Per METRICS_DEFINITION §L.)

---

## 2026-07-16 — H4 Payment Fee Coverage % rebased to revenue-order basis

- **Metric:** H4 Payment Fee Coverage % (and the §J/§K payment-fee gating chip that reads it).
- **Old formula:** `COUNT(fact_order WHERE payment_fee_usd IS NOT NULL) / COUNT(fact_order)` — over **all** orders.
- **New formula:** `COUNT(revenue orders WHERE payment_fee_usd IS NOT NULL) / COUNT(revenue orders)`, where a *revenue order* has ≥1 `is_revenue_status` line — the **same denominator basis as H1 Cost Coverage** (established in commit `727055c`). The all-orders figure is retained as the informational column `all_order_coverage_pct`.
- **Effect on live FOS data:** coverage reads **98.03%** (3,740 / 3,815 revenue orders) instead of **79.50%** (3,782 / 4,757 all orders). Tier flips from `< 80%` (chip active) to `≥ 80%` (chip off).
- **Reason:** The all-orders denominator counted **900 failed/cancelled/pending orders** that never settled a payment — so no PayPal/Stripe gateway fee was ever charged and their `payment_fee_usd` is correctly NULL. Counting those as "uncovered" understated coverage and falsely tripped the "estimated payment fee" chip. Profit (and therefore the fee gate) is only defined for revenue orders, so the denominator must match — exactly the reasoning behind the H1 cost-coverage rebasing. The genuine capture gap is only **75 revenue orders** where Woo's payload lacked a parseable plugin fee (of which the CSV `Fee` fallback backfills ~70 in `mart_order_profit`).
- **Files touched:** `dbt/models/marts/reconciliation/recon_payment_fee_coverage.sql`, `dbt/tests/singular/assert_payment_fee_coverage_at_least_80.sql`, `docs/METRICS_DEFINITION.md` (§H4, §J), `docs/WOO_PAYLOAD_AUDIT.md` (§6 coverage note), `docs/DASHBOARD_SPEC.md` (§K), `powerbi/measures/dax_measures.txt`, `powerbi/BUILD_GUIDE.md`, `powerbi/VERIFY_5_orders.md`.
- **Verification:** `dbt build --select recon_payment_fee_coverage assert_payment_fee_coverage_at_least_80` → PASS=2 WARN=0 ERROR=0 (the test no longer warns). The raw 79.5% plugin-capture rate over all orders remains documented in `WOO_PAYLOAD_AUDIT.md` as the true source-capture fact.
