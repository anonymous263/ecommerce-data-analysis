# Dashboard Specification — Power BI

> Pages activate only when their source data is loaded. Profit metrics are tier-gated by cost coverage.

---

## 0. Conventions

- All money in USD.
- Default date filter: last 30 days; sticky page-level filters for **site** and **country**.
- Tooltips on every KPI link to [METRICS_DEFINITION.md](METRICS_DEFINITION.md).
- DAX measures in a `_Measures` table.
- Star relationships dim → fact, single direction.
- Every page has a **Data Quality** strip showing relevant coverage % (cost, payment fee, fulfillment, GA4 match).

### Activation matrix (model vs dashboard)

| Page | Model-available | Dashboard-visible | Notes |
|---|---|---|---|
| 1 Executive Overview (sales) | Phase 2 | **Phase 4** | Profit cards tier-gated by Cost Coverage (§K) |
| 2 Product Performance | Phase 2 | **Phase 4** | Product profit shows caveat tag when cost is allocated |
| 3 Country / Market Performance | Phase 2 | **Phase 4** | |
| 4 Customer / Repeat Purchase | Phase 2 | **Phase 4** | Guest-checkout disclosure |
| 5 Fulfillment / Operations | Phase 5 | **Phase 5** | Hidden until enrichment loaded |
| 6 Website Behavior / GA4 Funnel | Phase 6 | **Phase 6** | Tracking-gap disclosure |
| 7 Landing Page Performance | Phase 6 | **Phase 6** | |
| 8 Marketing (paid ROAS/MER/CAC) | Optional Future | Optional Future | Hidden in MVP |
| 9 Data Quality (sub-page) | Phase 2 | **Phase 4** | Coverage + reconciliation views |

Pages not yet dashboard-visible are hidden in the published `.pbix`.

---

## 1. Page 1 — Executive Overview

**Purpose:** five-second health check.

**KPI cards:**
- Revenue (USD), MoM %
- Net Revenue, MoM %
- Orders
- AOV
- **Shipping Charged to Customer** (USD), MoM %
- Refund Rate (order-level)
- Cancellation Rate
- *(tier-gated by Cost Coverage §K)* Contribution Profit, MoM %; Profit Margin; ROI

**Charts:**
1. Line — Revenue + Contribution Profit (when visible), daily, last 90d.
2. Clustered bar — Revenue + Profit by Site.
3. Horizontal bar — Top 10 countries by Revenue.
4. Histogram — order count by profit margin bucket (profit-gated).
5. Card — open backlog (`status='processing'`) — available from Phase 4.

**Phase 6 additions:** sessions and conversion-rate cards from GA4.
**Optional Future:** MER + blended ROAS cards.

**Data Quality strip on this page:**
- Cost coverage %, Payment fee coverage %, Payment fee source mix.

**Profit caveat banner (must appear whenever any profit visual is shown):**
> Customer shipping charge is counted as revenue. COGS is the all-in per-order fulfilment cost (already includes supplier fulfillment/shipping fee), so shipping is never subtracted as a cost. Revenue is net of refunds. *(Approach A — see `docs/METRIC_CHANGES.md`.)*

---

## 2. Page 2 — Product Performance

**KPI cards:** distinct products sold; avg units/order; best-selling product by units / revenue / profit (when profit visible).

**Charts:**
1. Table + sparkline — Top 20 products by Contribution Profit (or Revenue if profit unavailable), last 8 weeks.
2. Scatter — Revenue vs Margin (or Revenue vs AOV when profit unavailable).
3. Donut — Revenue share by `product_type`.
4. Bar — top 15 design topics.
5. Small multiples — product launch date → cumulative revenue.

**Caveat tag on every product profit visual:** when `mart_product_profit.cost_allocation_method != 'line_exact'`, display a yellow chip "Profit allocated by revenue share — not exact line-level cost" linking to [DATA_MODEL.md §4.3](DATA_MODEL.md).

---

## 3. Page 3 — Country / Market Performance

**KPI cards:** top country by revenue; top country by margin (when profit visible); country count.

**Charts:**
1. Map — bubble = revenue, color = margin % (gray if profit unavailable).
2. Sortable table — orders, revenue, AOV, margin %, refund rate, **Shipping Charged Ratio** by country.
3. Bar — **Shipping Charged Ratio by country** = `SUM(shipping_charged_usd) / SUM(line_revenue_usd)`. **Labeled "shipping charged to customer / revenue", not "shipping cost".**
4. Bar — refund rate by country (hide < 10 orders).

---

## 4. Page 4 — Customer / Repeat Purchase

**KPI cards:** distinct customers; repeat customer share; orders per customer; repeat revenue share.

**Charts:**
1. Cohort retention heatmap — first-order month × subsequent months.
2. Stacked bar — repeat vs new orders, monthly.
3. Customers per country table.

**Disclosures (must be on the page):**
- Guest checkout — identity reconstructed via hashed normalized billing email.
- One person/two emails = two customers; shared inbox = one customer; typos create duplicates.
- Customer-level rows are private; public portfolio uses fully synthetic data.

---

## 5. Page 5 — Fulfillment / Operations *(Phase 5)*

**KPI cards:** avg fulfillment days; on-time fulfillment %; open backlog; avg delivery days (if available).

**Charts:**
1. Supplier scorecard table.
2. Carrier delivery time — box plot or bar.
3. Backlog age — bar bucketed by days in `processing`.
4. Heatmap — delays by country.

**Data Quality strip:** fulfillment enrichment coverage %.

---

## 6. Page 6 — Website Behavior / GA4 Funnel *(Phase 6)*

**KPI cards:** Sessions; Users; Engagement Rate; Pages/Session; Avg Engagement Time/Session; Purchase Conversion Rate.

**Charts:**
1. Sessions trend, line, last 90d.
2. Users trend, line, last 90d.
3. Funnel — Sessions → view_item → add_to_cart → begin_checkout → purchase.
4. Device breakdown — Sessions + Conv Rate.
5. Country breakdown table.
6. Engagement rate trend.

**Disclosure:** "GA4 numbers are tracking-based and will not match WooCommerce orders exactly. See Data Quality page for GA4↔Woo match rate. Attribution active/disabled per [GA4_BIGQUERY_AUDIT.md](GA4_BIGQUERY_AUDIT.md)."

---

## 7. Page 7 — Landing Page Performance *(Phase 6)*

**Charts:**
1. Landing page table — sessions, conv rate, revenue, RPC.
2. Scatter — sessions vs conv rate.
3. Sankey — top 5 page paths.
4. Pageviews leaderboard.

---

## 8. Page 8 — Marketing (paid spend) *(Optional Future only)*

**Hidden in MVP.** Activated only if ads ever run. ROAS, MER, CAC, CPC, CPM hidden until ads data exists.

---

## 9. Page 9 — Data Quality (sub-page)

Always-on operational dashboard:

- **Cost Coverage %** with tier indicator (red <80% / yellow 80–95% / green ≥95%)
- **Cost Allocation Coverage %**, **COGS Coverage %**
- **Payment Fee Coverage %** with source split (`api_exact` / `plugin_parser` / `seed_estimate` / `missing`)
- Fulfillment Enrichment Coverage % (Phase 5)
- GA4 ↔ Woo order count ratio (Phase 6)
- GA4 `transaction_id` match rate (Phase 6) with the activation gate marker
- CSV vs Woo revenue daily drift
- CSV vs dbt profit daily drift
- Woo vs CSV shipping-charged daily drift

---

## 10. Cross-page design

- One synced date filter; one synced site filter.
- Tooltips on every KPI show formula + caveat + source.
- Accessible colors; site comparison via shape/pattern, not color alone.
- A "Definitions" page links back to [METRICS_DEFINITION.md](METRICS_DEFINITION.md).

---

## 11. Power BI Artifacts

```
powerbi/
├── ecommerce_analytics.pbix
├── measures/
│   └── dax_measures.txt
├── themes/
│   └── ecommerce_theme.json
└── screenshots/
```

---

## K. Tier-Gated Profit Visibility (locked)

Per [METRICS_DEFINITION.md §J](METRICS_DEFINITION.md), profit cards and charts in this dashboard obey the following tiers, driven by the live Cost Coverage % measure:

| Cost Coverage % | UI behavior |
|---|---|
| `< 80%` | All profit visuals **hidden**; banner: "Profit unavailable — cost coverage too low" on Executive Overview. |
| `80% – 95%` | Profit visuals visible with a yellow chip: "Partial cost coverage (XX%) — numbers are usable but not owner-trusted". |
| `≥ 95%` | Fully trusted; no chip. |

Additionally, if Payment Fee Coverage % (revenue-order basis, see [METRICS_DEFINITION.md §H4](METRICS_DEFINITION.md)) is `< 80%`, every profit visual gets a second chip: "Estimated payment fee — XX% from `seed_estimate` or `missing`". *(Live FOS: 98.03% → chip off.)*
