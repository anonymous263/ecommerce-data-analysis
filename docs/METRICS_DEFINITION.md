# Metrics Definition

> Single source of truth for every metric used in dashboards. Every metric has business meaning, formula, **source**, **model-available phase**, **dashboard-visible phase**, and caveats. If a metric is not here, it is not allowed on a dashboard.

> **Currency rule:** all money in USD, normalized in dbt staging per order using `seeds/fx_rates.csv` (replaceable by FX API later). `*_src` columns kept alongside for audit.

> **Two phase fields:**
> - **Model-available** = the dbt model that produces this metric exists and is tested.
> - **Dashboard-visible** = the Power BI page that shows this metric is unhidden.

---

## A. Sales Metrics
*Source: WooCommerce. **Model-available: Phase 2.** **Dashboard-visible: Phase 4.***
*Tables: `marts_core.fact_order`, `fact_order_item`, `fact_refund`.*

### A1. Revenue (gross)
- **Formula:** `SUM(fact_order_item.line_revenue_usd) WHERE is_revenue_status`
- **Caveats:** Gross of refunds. Revenue counts only orders with `is_revenue_status = true` (Woo status `completed`/`processing`/`refunded`, per `WOO_PAYLOAD_AUDIT.md` §5) — `failed`/`cancelled`/`pending` orders are excluded even though their line items still carry a non-null `line_revenue_usd`. CSV `Revenue` is not used — drift only in `recon_csv_vs_dbt_revenue`.

### A2. Net Revenue
- **Formula:** `Revenue − SUM(fact_refund.refund_amount_usd)`
- **Caveats:** Refunds booked on refund date.

### A3. Orders
- **Formula:** `COUNT(DISTINCT fact_order.order_sk) WHERE status IN ('processing','completed','on-hold')`

### A4. Quantity Sold
- **Formula:** `SUM(fact_order_item.quantity)`

### A5. AOV
- **Formula:** `Revenue / Orders`

### A6. AIV
- **Formula:** `Revenue / Quantity Sold`

### A7. Shipping Charged to Customer
- **Source:** WooCommerce official; CSV is reconciliation only.
- **Formula:** `SUM(fact_order.shipping_charged_usd)`
- **Caveats:** This is **revenue-side** (what the customer paid for shipping). It is **not** a cost. Supplier shipping fee is inside `cogs_usd`. The CSV `Shipping` column represents the same concept and is compared in `recon_woo_vs_csv_shipping_charged`.

### A8. Shipping Charged / Revenue
- **Formula:** `SUM(shipping_charged_usd) / SUM(line_revenue_usd) WHERE is_revenue_status` (denominator = A1 Revenue)
- **Use:** spot countries where shipping is a large share of order value (priced-in vs not).

---

## B. Profitability Metrics
*Source: dbt-computed from Woo revenue + manual CSV cost enrichment.*
*Tables: `mart_order_profit`, `mart_product_profit`, `mart_country_profit`, `fact_order`, `fact_order_cost`.*
***Model-available: Phase 3. Dashboard-visible: Phase 4, gated by cost coverage (see §J).***

### B1. COGS
- **Source:** `fact_order_cost.cogs_usd` (manual sheet).
- **Important:** COGS **already includes the supplier fulfillment/shipping fee** where applicable. Do not subtract a separate shipping cost in any profit formula.
- **Fallback:** `seeds/product_cogs.csv` (legacy fallback only, not primary).

### B2. Payment Fee
- **Source priority** (mapped to `payment_fee_source` on `fact_order`):
  1. `'api_exact'` — direct field in Woo API (audit-confirmed).
  2. `'plugin_parser'` — parsed from a plugin-specific location per [WOO_PAYLOAD_AUDIT.md §6](WOO_PAYLOAD_AUDIT.md).
  3. `'seed_estimate'` — fall back to `dbt/seeds/payment_fees.csv` keyed on payment method + country.
  4. `'missing'` — `payment_fee_usd = NULL`, `payment_fee_needs_review = TRUE`.
- **Formula:** `SUM(fact_order.payment_fee_usd)`
- **Dashboard rule:** if `seed_estimate` + `missing` exceeds 20% of orders in the view, profit cards display an "estimated payment fee" warning chip.

### B3. Design Fee
- **Source:** `fact_order_cost.design_fee_usd` (manual sheet).

### B4. Gross Profit
- **Formula:** `Revenue − COGS`

### B5. Contribution Profit *(locked formula)*
- **Formula:**
  ```
  Contribution Profit = Revenue − COGS − Payment Fee − Design Fee
  ```
- **Critical caveat (must appear on every profit visual):**
  > COGS from the manual sheet **already includes** supplier fulfillment/shipping fee where applicable, so shipping cost is **not** subtracted again. The CSV `Shipping` column is the *customer* shipping charge, not a supplier cost.

### B6. Profit Margin
- **Formula:** `Contribution Profit / Revenue`

### B7. ROI (POD definition)
- **Formula:** `Contribution Profit / COGS`
- **Caveats:** dbt-calculated only. CSV's `ROI` column is never used.

### B8. Product-Level Profit (caveated)
- Computed via cost allocation in `mart_product_profit`.
- Each row carries `cost_allocation_method` + `cost_confidence`.
- Dashboards display a yellow chip whenever `cost_allocation_method != 'line_exact'`.

---

## C. Refund / Cancellation Metrics
*Source: WooCommerce. **Model-available: Phase 2.** **Dashboard-visible: Phase 4.** Order-level grain in Phase 1–6.*

### C1. Refunded Order Count
`COUNT(*) FROM fact_refund`

### C2. Refund Amount
`SUM(refund_amount_usd)`

### C3. Refund Rate (order-level)
- **Formula:** `COUNT(refunded_or_cancelled_orders) / COUNT(eligible_orders)`
- "Eligible" = orders not in `failed` / `pending`.

### C4. Cancellation Rate
- **Formula:** `COUNT(status='cancelled') / COUNT(eligible_orders)`

### C5. Refund Revenue Share
- **Formula:** `Refund Amount / Revenue`

### C6. Item-Level Refund Rate *(future / conditional)*
- Activates only if the Phase 1 Woo payload audit confirms item-level refund data.
- **Formula:** `COUNT(fact_refund WHERE order_item_sk IS NOT NULL) / COUNT(fact_order_item)`

---

## D. Fulfillment & Operations Metrics
*Source: manual CSV (Phase 5); later Printify/carrier APIs.*
***Model-available: Phase 5. Dashboard-visible: Phase 5.***

### D1. Fulfillment Delay
`ship_date − order_date` (calendar days)

### D2. Delivery Delay
`deliver_date − ship_date`. Hidden until carrier API integrated.

### D3. On-Time Fulfillment Rate
`COUNTIF(fulfillment_days <= dim_supplier.sla_days) / COUNT(*)`

### D4. Open Order Backlog
`COUNT(orders WHERE status='processing')` from `fact_order` — **available in Phase 4 even without Phase 5**.

### D5. Check Sent Rate
Share of orders with `check_sent = TRUE` in `fact_fulfillment`.

---

## E. GA4 Behavior Metrics
*Source: GA4 BigQuery. **Model-available: Phase 6. Dashboard-visible: Phase 6.***

E1–E14 unchanged from prior revision: Sessions, Users, New Users, Pageviews, Pages/Session, Engagement Rate, Avg Engagement Time, Landing Page Sessions, Product Views, Add-to-Cart Rate, Checkout Rate, Purchase Conversion Rate, Funnel Conversion (stepwise), Conversion Rate.

### E15. GA4 transaction_id Coverage *(Phase 6 audit gate — see [GA4_BIGQUERY_AUDIT.md](GA4_BIGQUERY_AUDIT.md))*
- **Formula:** `COUNT(purchase WHERE transaction_id IS NOT NULL) / COUNT(purchase)`
- If <85%: attribution disabled; GA4 used for funnel + landing pages only.

---

## F. Marketing Metrics
*Source: Ads platforms + GA4 + Woo. **Optional Future only — not part of MVP.***

F1 Sessions by Channel — model-available + dashboard-visible from Phase 6 (GA4 only, no spend).
F2 Conversion Rate by Channel — same.

**F3 ROAS / F4 MER / F5 CAC / F6 CPC/CPM:** hidden until ads data exists. No portfolio gate depends on these.

---

## G. Site & Geography Metrics
*Source: WooCommerce. **Model-available: Phase 2. Dashboard-visible: Phase 4.***

### G1. Revenue per Site
`SUM(line_revenue_usd) WHERE is_revenue_status GROUP BY site_sk` (= A1 Revenue, grouped)

### G2. Revenue per Country
`SUM(line_revenue_usd) WHERE is_revenue_status GROUP BY country_sk` (= A1 Revenue, grouped)

### G3. AOV per Country
- Sample-size guard: hide countries with < 10 orders.

### G4. Shipping Charged Ratio by Country
- **Formula:** `SUM(shipping_charged_usd) / SUM(line_revenue_usd) WHERE is_revenue_status GROUP BY country_sk`
- **Not** a cost ratio — this is what customers are *paying for shipping* relative to revenue.

---

## H. Data Quality & Coverage Metrics
*dbt-computed in `marts_recon`. Visible on a "Data Quality" sub-page.*

| Metric | Formula | Target | Model phase | Dashboard phase |
|---|---|---|---|---|
| H1. Cost Coverage % | `COUNT(revenue orders with fact_order_cost) / COUNT(revenue orders)` where *revenue order* = has ≥1 `is_revenue_status` line. Profit only applies to revenue orders, so dead failed/cancelled orders are excluded from the denominator. `all_order_coverage_pct` (÷ all orders) is kept as an informational column. | tiered, see §J | 3 | 4 |
| H2. Cost Allocation Coverage % | `COUNT(line items with cost_allocation_method='line_exact') / COUNT(fact_order_item)` | informational | 3 | 4 |
| H3. COGS Coverage % | `COUNT(fact_order_cost WHERE cogs_usd IS NOT NULL) / COUNT(fact_order)` | ≥ 80% | 3 | 4 |
| H4. Payment Fee Coverage % | `COUNT(fact_order WHERE payment_fee_usd IS NOT NULL) / COUNT(fact_order)` | ≥ 80% | 2 | 4 |
| H4b. Payment Fee Source Mix | `COUNT BY payment_fee_source / COUNT(*)` | informational | 2 | 4 |
| H5. Fulfillment Enrichment Coverage % | `COUNT(orders with fact_fulfillment) / COUNT(fact_order)` | ≥ 80% | 5 | 5 |
| H6. GA4 ↔ Woo Order Count Ratio | `COUNTIF(ga4.purchase, day) / COUNT(woo.orders, day)` | report only | 6 | 6 |
| H7. GA4 transaction_id Match Rate | `COUNT(ga4.purchase joined to fact_order) / COUNT(ga4.purchase)` | gate at 85% | 6 | 6 |
| H8. CSV vs Woo Revenue Drift | `(csv.revenue − A1 Revenue) / A1 Revenue` (Woo side filtered `WHERE is_revenue_status`) | report only | 3 | 4 |
| H9. CSV vs dbt Profit Drift | `(csv.profit − mart_order_profit.contribution_profit_usd) / mart_order_profit.contribution_profit_usd` | report only | 3 | 4 |
| H10. Woo vs CSV Shipping Charged Drift | `(csv.shipping − fact_order.shipping_charged_usd) / fact_order.shipping_charged_usd` | report only | 3 | 4 |

---

## I. Customer Metrics
*Source: WooCommerce + hashed billing email. **Model-available: Phase 2. Dashboard-visible: Phase 4.***
*Table: `mart_customer_summary`.*

### I1. Distinct Customers
`COUNT(DISTINCT customer_hash WHERE NOT is_unknown_email)`

### I2. Repeat Customer Share
`COUNT(customer_hash WHERE total_orders > 1) / COUNT(customer_hash)`

### I3. Orders per Customer
`Orders / Distinct Customers`

### I4. Repeat Revenue Share
`SUM(revenue from orders where customer.total_orders > 1) / Revenue`

**Caveats (must be on dashboard):**
- All sites use guest checkout; identity is reconstructed from hashed billing email.
- One person/two emails = two customers; shared inbox = one customer; typos create duplicates.
- Customer-level data is private only; never published.

---

## J. Profit Dashboard Gating by Cost Coverage

**Tiered visibility for profit metrics (B1–B8):**

Cost Coverage % here is H1 measured over **revenue orders** (see H1 note) — not all orders — because profit is only defined for orders that generated revenue.

| Cost Coverage % (H1, revenue-order basis) | Profit metric visibility | UI treatment |
|---|---|---|
| `< 80%` | **Hidden** | Profit cards and charts hidden in the published `.pbix`; a "Profit unavailable — cost coverage too low" banner appears on the Executive Overview page. |
| `80% – 95%` | **Visible with warning** | Cards/charts shown, but every profit visual gets a yellow "Partial cost coverage (XX%)" chip. Numbers are usable but not owner-trusted. |
| `≥ 95%` | **Fully trusted** | Visible without warning. Owner-facing profit dashboard considered authoritative. |

Additionally, if **Payment Fee Coverage (H4)** is `< 80%`, all profit visuals add a second chip: "Estimated payment fee — XX% from `seed_estimate` or `missing`".

---

## K. Activation Matrix

| Phase | Model-available | Dashboard-visible |
|---|---|---|
| 2 | A1–A6, A7, A8, C1–C5, G1–G4, H4, I1–I4 | (none — Power BI not yet built) |
| 3 | + B1–B8 (computed), H1–H3, H4b, H8–H10 | (still none) |
| 4 | (same as 3) | A1–A8, **B1–B8 gated by §J**, C1–C5, G1–G4, I1–I4, H1–H4b, H8–H10 |
| 5 | + D1, D3, D5, H5 | + D1, D3, D5, H5 |
| 6 | + E, H6, H7 | + E, H6, H7 |
| Optional Future | + F3–F6 | + F3–F6 |

---

## L. Metric Ownership

- The owner-analyst owns these definitions.
- Changes go in `docs/METRIC_CHANGES.md` with date, old formula, new formula, reason.
- DAX measure `Description` fields cross-link here.
- dbt `schema.yml` `description` fields cross-link here.
