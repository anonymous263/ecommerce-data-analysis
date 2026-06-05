# Data Audit — Phase 0

> Inventory of every data input. WooCommerce is the source of truth for revenue/orders. The manual Order Management sheet is the source of truth (for now) for COGS (which already includes supplier fulfillment/shipping fee), design fee, and operational fields. GA4 is the source of truth for behavior. Maven sample is practice/demo only.

---

## 1. Source Inventory & Ownership

| Source | Role | Lives where |
|---|---|---|
| **WooCommerce REST API** | **Source of truth** for orders, items, customers, products, coupons, refunds, status, **customer shipping charge** | Remote per site → `raw.woo_*` |
| **GA4 BigQuery export** | **Source of truth** for sessions, events, funnel, landing pages, traffic source | Remote (GCP) → `raw.ga4_*` |
| **`Order Management.csv` / Sheet** | **Source of truth (interim)** for COGS (incl. supplier shipping), design fee, supplier, tracking, fulfillment fields | Local + Google Sheet, **gitignored** |
| Maven Fuzzy Factory sample | Practice + public demo only | Local + safe to publish |
| Ads platforms | Spend / impressions / clicks | None running — **Optional Future** |

**Hard rules:**
- WooCommerce owns revenue, orders, refunds, status, and customer shipping charge (`shipping_charged_*`).
- The manual CSV is the only place COGS exists today, **but**:
  - the CSV's `Revenue`, `Profit`, `ROI`, `Profit Margin` columns are **never copied into marts** as official metrics;
  - the CSV's `Shipping` column is **customer shipping charge**, not supplier cost. It is loaded for reconciliation only (`recon_woo_vs_csv_shipping_charged`).
  - the supplier fulfillment/shipping fee is **inside `CoGS`** in the manual sheet — there is no separate "actual shipping cost" field.
- Maven sample lives in an isolated namespace and never mixes with real Woo marts.

---

## 2. Detected Local Files & Folders

```
Ecommerce/
├── Order Management.csv                     # gitignored; cost + fulfillment enrichment
└── E-commerce data sample/                  # practice/demo only
    ├── orders.csv
    ├── order_items.csv
    ├── order_item_refunds.csv
    ├── products.csv
    ├── website_sessions.csv
    ├── website_pageviews.csv
    └── [Đọc cái này trước] Tài liệu Data Dictionary.docx
```

**Present in repo (planning placeholders):**
- `docs/WOO_PAYLOAD_AUDIT.md` — placeholder; filled during Phase 1.
- `docs/GA4_BIGQUERY_AUDIT.md` — placeholder; filled during Phase 6.

**Not present yet:**
- `.env`, `.env.example`
- `config/sites.yaml`
- `dbt/seeds/dim_site_seed.csv`
- BigQuery service account JSON
- WooCommerce consumer keys per site
- `docker-compose.yml`, `dbt/`

---

## 3. WooCommerce REST API (Source of Truth — Phase 1)

### 3.1 Endpoints to pull (per site)
| Endpoint | Use |
|---|---|
| `GET /wp-json/wc/v3/orders` | Order header (status, totals, currency, line_items, shipping total) |
| `GET /wp-json/wc/v3/orders/<id>/refunds` | Refunds per order (audit confirms grain) |
| `GET /wp-json/wc/v3/products` | Product catalog |
| `GET /wp-json/wc/v3/products/<id>/variations` | Variations |
| `GET /wp-json/wc/v3/customers` | Customer registry (most rows expected to be guests with `id=0`) |
| `GET /wp-json/wc/v3/coupons` | Coupon master |
| `GET /wp-json/wc/v3/reports/sales` | Reconciliation only |

### 3.2 Multi-site
- Every raw/staging/mart row carries `site_code` (text) and/or `site_sk` (int).
- Order natural key: `site_code + woo_order_id`.
- `config/sites.yaml` (Python ELT) + `dbt/seeds/dim_site_seed.csv` (dbt) must list the same sites.

### 3.3 Incremental strategy
- `modified_after=<ISO8601>` per entity.
- Watermark per `(pipeline, site_code, entity)` in `raw.pipeline_state`.

### 3.4 Unknowns to resolve in `docs/WOO_PAYLOAD_AUDIT.md` (Phase 1)
- Acowebs Custom Product Addons `meta_data` keys for size/type/color/addons.
- Payment fee field location (gateway wrapper plugin); mapping to `payment_fee_source` enum.
- Refund grain (order vs item).
- Which top-level field carries customer shipping charge → maps to `shipping_charged_*`.
- Custom order statuses.
- Currency variability per site.

### 3.5 Privacy (PII to drop or hash before staging)
| Endpoint | PII fields |
|---|---|
| `orders` | `billing.*`, `shipping.*`, `customer_ip_address`, `customer_user_agent` |
| `customers` | `email`, `first_name`, `last_name`, `billing.*`, `shipping.*`, `username` |

**Customer linkage rule:**
```
customer_hash = SHA-256( lower(trim(billing_email)) || PII_SALT )
```
- Missing email → `unknown:<site_code>:<woo_order_id>` (non-mergeable).
- Caveats: one person/two emails = two customers; shared inbox = one customer; typos create duplicates.
- Customer-level outputs are private. **No hashed real-customer rows appear in the public portfolio.**

---

## 4. Manual `Order Management.csv` / Sheet (Cost + Fulfillment Enrichment — Phases 3 & 5)

### 4.1 Role
- COGS (including supplier fulfillment/shipping fee), design fee, supplier, tracking, operational flags.
- **CSV `Shipping` = customer shipping charge** (not supplier cost). Loaded for reconciliation only.
- Revenue / Profit / ROI / Profit Margin from the CSV are observed for drift but never official.

### 4.2 Columns — what's used vs not

**Used as cost / payment-fee fallback enrichment:**

| CSV column | Mapped to | Phase |
|---|---|---|
| `CoGS` | `cogs_usd` in `fact_order_cost` (includes supplier shipping fee) | 3 |
| `Design fee` | `design_fee_usd` in `fact_order_cost` | 3 |
| `Fee` | `payment_fee_fallback_usd` (only used when Woo payload audit returns `seed_estimate`/`missing`) | 3 |

**Used for operational fulfillment (Phase 5):**

| CSV column | Mapped to |
|---|---|
| `Supplier` (e.g. `#17969421.1207`) | `supplier_store_id` + `supplier_order_id` in `fact_fulfillment` |
| `Fulfill URL` | `fulfill_url_hash` |
| `Tracking ID` | `tracking_id_hash` |
| `Tracking Deliver URL` | `tracking_url_hash` |
| `Shipping Company` | `shipping_company` |
| `Check Sent` | `check_sent` |
| `Note` | `note_present` (raw note kept only in `raw.csv_order_management`) |

**Used as join keys (not source of truth):**

| CSV column | Use |
|---|---|
| `Date`, `Status`, `Project`, `Order Code` | Join keys to Woo |

**Loaded for reconciliation only (never official metrics):**

| CSV column | Mapped to | Recon view |
|---|---|---|
| `Revenue` | `csv_revenue_observed_usd` | `recon_csv_vs_dbt_revenue` |
| `Profit` | `csv_profit_observed_usd` | `recon_csv_vs_dbt_profit` |
| `Shipping` (customer shipping charge) | `csv_shipping_charged_usd` | `recon_woo_vs_csv_shipping_charged` |
| `ROI`, `Profit Margin` | (informational drift only) | included in `recon_csv_vs_dbt_profit` |

**Dropped at load:**

| CSV column | Why |
|---|---|
| `Name`, `Email`, `Phone`, `Ship to` | PII |
| `Day`, `Month`, `Year`, `Total New Order` | Redundant / aggregate |

### 4.3 Privacy rules for the CSV
- Real CSV is **gitignored**, never committed.
- `raw.csv_order_management` is **private-only, local-only, gitignored, never exported, never used in the public sample**.
- **Manual CSV PII rule:** for the manual Order Management CSV, unnecessary PII columns such as `Name`, `Email`, `Phone`, and `Ship to` are dropped **before** loading into `raw.csv_order_management`. Therefore `raw.csv_order_management` is **not** a byte-for-byte copy of the full sheet; it is a private raw operational extract with PII removed at ingestion. Tracking IDs and fulfillment URLs may be loaded to raw but **must** be hashed before staging/marts.
- Synthetic equivalents are used for any public demo.

### 4.4 Validation requirements before Phase 4 trusts profit
- Cost coverage ≥ 80% (tiered gating per [METRICS_DEFINITION.md §J](METRICS_DEFINITION.md)).
- CSV-vs-Woo revenue daily delta per site ≤ 5%.
- Woo-vs-CSV shipping-charged daily delta per site ≤ 5%.
- Hand-reconcile 5 sample orders end-to-end.

### 4.5 Data quality issues to handle on load
| # | Issue | Handling |
|---|---|---|
| Q1 | Header summary rows at rows 2–3 | `pd.read_csv(skiprows=[1,2])` |
| Q2 | Multi-row orders with blank financials in child rows | Forward-fill order-level keys |
| Q3 | Column names with diacritics / trailing spaces | Normalize on load |
| Q4 | Currency symbols / whitespace in numeric columns | Strip and parse |
| Q5 | `Country` not ISO (`UK` vs `GB`) | Used only for cross-check |
| Q6 | Phone scientific notation | Drop entirely (PII) |
| Q7 | Composite `Type` (`M | T-Shirt`) | Parsed only as backup if Acowebs audit gives us better |

---

## 5. `E-commerce data sample/` (Maven Fuzzy Factory — Practice / Demo Only)

Practice dataset. Lives in its own namespace (`raw.maven_*` / `marts_demo.*`). Used in Phase 0 for SQL practice and as a second public dataset in Phase 7. **Never** loaded into `marts_core` or any real-data mart.

Tables: `orders` (~32K), `order_items` (~40K), `order_item_refunds` (~1.7K), `products` (4), `website_sessions` (~472K), `website_pageviews` (~1.19M), plus a Vietnamese data dictionary `.docx`.

---

## 6. Planned GA4 BigQuery Audit (Phase 6 — Data Not Local Yet)

The detailed GA4 audit lives in [`docs/GA4_BIGQUERY_AUDIT.md`](GA4_BIGQUERY_AUDIT.md) — that placeholder exists and is filled in Phase 6. It covers tables, event names, ecommerce coverage, purchase events, **`transaction_id` coverage and match rate** vs Woo, traffic source fields, item array coverage, and records the **activation decision** (attribution active vs disabled).

---

## 7. Summary — What to Collect Next

| Need | Where |
|---|---|
| WooCommerce consumer key/secret per site | WP admin |
| Full site list with currency, source site timezone, and reporting timezone | Owner knowledge → `config/sites.yaml` + `dim_site_seed.csv` |
| Live Woo API responses for 20 recent orders per site | Phase 1 audit → `docs/WOO_PAYLOAD_AUDIT.md` |
| FX rate source (initial seed) | ECB daily or hard-coded seed → `dbt/seeds/fx_rates.csv` |
| Ads platform tokens | Not required for MVP |
| BigQuery project + dataset + service account | Phase 6 |
