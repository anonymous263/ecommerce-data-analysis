# Data Model — Star Schema (WooCommerce + Cost Enrichment + GA4)

> Dimensional model. WooCommerce owns revenue/orders/refunds/customer-shipping-charge. The manual sheet owns COGS (which already includes supplier fulfillment/shipping fee), design fee, and operational fulfillment fields. GA4 owns behavior. Profit is computed in marts; CSV `Profit` is never copied as official.

---

## 1. Why a Star Schema

- **Dim tables** = nouns (products, customers, dates, countries).
- **Fact tables** = verbs (one order item, one refund, one GA4 event).
- All relationships are single-direction (dim → fact) on surrogate keys.

---

## 2. Grain Statements (CRITICAL — write these first)

| Fact / mart | Source of truth | Grain |
|---|---|---|
| `fact_order` | **WooCommerce** | one order header (`site_code + woo_order_id`) |
| `fact_order_item` | **WooCommerce** | one product line in an order |
| `fact_refund` | **WooCommerce** | one refund/cancellation per Woo order (order-level grain) |
| `fact_order_cost` | **Manual CSV** (Phase 3) | one row per Woo order (order-level cost) |
| `fact_fulfillment` | **Manual CSV** (Phase 5); later Printify/carrier APIs | one shipment per Woo order |
| `mart_order_profit` | dbt-computed | one Woo order |
| `mart_product_profit` | dbt-computed | one order × line item (with allocated cost) |
| `mart_country_profit` | dbt-computed | one country × period |
| `mart_customer_summary` | dbt-computed | one `customer_hash` |
| `fact_ga4_event` | **GA4** | one event |
| `fact_ga4_session` | **GA4** (derived) | one session |
| `fact_ga4_pageview` | **GA4** | one `page_view` event |
| `fact_ga4_ecommerce_event` | **GA4** | one ecommerce event × item |
| `fact_ad_spend_daily` | **Ads** (Optional Future) | site × channel × campaign × day |

---

## 3. Official Revenue Source (locked)

**Product revenue** lives **once**, at `fact_order_item`:

```
Product Revenue (USD)  =  SUM(fact_order_item.line_revenue_usd)
Quantity Sold          =  SUM(fact_order_item.quantity)
```

`fact_order` keeps order-header amounts (`shipping_charged_usd`, `discount_usd`, `tax_usd`, `payment_fee_usd`) but **no product-revenue column** — analysts roll up product revenue from `fact_order_item`. This prevents the order × item double-count.

**Customer shipping charge is the second revenue component.** `fact_order.shipping_charged_usd` is money the customer paid the store and is counted as revenue in the profit base (Approach A — see §4). It lives once, at order grain, and is added to product revenue only in `mart_order_profit` (`gross_revenue_usd = product + shipping`); it is never merged back into `fact_order_item`.

The CSV's `Revenue` column is never read into a mart. It appears in `marts_recon.recon_csv_vs_dbt_revenue` only.

---

## 4. Profit Calculation Model (Phase 3+)

Profit is **computed in dbt marts** by joining WooCommerce revenue with manual CSV cost enrichment.

### 4.1 Contribution profit formula (locked)

```
contribution_profit_usd =
    net_revenue_usd
  − cogs_usd          -- from manual CSV (column U); ALL-IN per-order fulfilment cost, INCLUDES supplier fulfillment/shipping fee
  − design_fee_usd    -- from manual CSV
  − payment_fee_usd   -- from Woo payload audit; fallbacks tracked via payment_fee_source

net_revenue_usd = gross_revenue_usd − effective_refund_usd
  gross_revenue_usd         = gross_product_revenue_usd + shipping_charged_usd   -- order-total revenue basis (Approach A)
  gross_product_revenue_usd = SUM(fact_order_item.line_revenue_usd) over the order, filtered by is_revenue_status
  shipping_charged_usd      = fact_order.shipping_charged_usd — customer shipping charge (revenue-side)
  refunds_usd               = SUM(fact_refund.refund_amount_usd) over the order (POSITIVE; 0 when none) — the TRUE amount returned, incl. shipping
  effective_refund_usd      = LEAST(refunds_usd, gross_revenue_usd) — the portion applied to the revenue base

Refund netting is CAPPED at gross revenue. Woo refunds are full-order (product + shipping + tax; confirmed against the data). Now that the revenue base ALSO includes shipping, refund and revenue are on the same order-total basis, so the cap almost never binds — it remains only as a floor-at-0 guard for the rare over-refund: a full refund reverses the sale to 0 (not below), and the order then shows a COGS loss — correct, because the item WAS produced before the refund (unlike failed/cancelled orders, which never incurred COGS).
```

**Why is customer shipping revenue? (Approach A, 2026-07-21)** `shipping_charged_usd` is money the customer paid the store — real income. `cogs_usd` (CSV column U) is the *all-in* per-order fulfilment cost, which already includes whatever the supplier charged to ship the item. The store both **charges** the customer for shipping and **pays** the supplier to fulfil, so both sides must appear in the P&L. The earlier formula subtracted the shipping-inclusive COGS while excluding the shipping the customer paid — an asymmetry that understated FOS profit by ~$40k (contribution profit $47.5k → $87.1k). See `docs/METRIC_CHANGES.md` (2026-07-21) and `CLAUDE.md` domain rules #1/#2/#4/#6.

**Why net of refunds?** `is_revenue_status` treats `'refunded'` orders as revenue-bearing (they did sell), so without subtracting `refunds_usd`, a refunded order would show full gross revenue and full positive profit despite the money having been returned to the customer. `revenue_usd` is exposed in `mart_order_profit` as an **alias of `net_revenue_usd`**, so any consumer reading "revenue_usd" gets the net figure. `fact_refund` (built in Phase 1/2, order-level grain) is consumed here.

**Supplier shipping is not a separate cost.** It is folded into `cogs_usd` (column U). Do not model a separate supplier-shipping term. If a future supplier/carrier API ever exposes it as a *distinct* number, both `cogs_usd` and this formula must be reworked together at that time — `cogs_usd` would shrink and a new `supplier_shipping_cost_usd` term would be added. Until then: do not model it. (Note this is the supplier-side cost — the customer-side shipping charge is already revenue above.)

### 4.2 Order-level profit (`mart_order_profit`)

```
mart_order_profit per Woo order:
  gross_product_revenue_usd = SUM(fact_order_item.line_revenue_usd) filtered by is_revenue_status
  shipping_charged_usd       = fact_order.shipping_charged_usd   -- customer shipping charge (revenue)
  gross_revenue_usd          = gross_product_revenue_usd + shipping_charged_usd  -- order-total basis
  refunds_usd                = SUM(fact_refund.refund_amount_usd) over order (0 when none) -- true amount returned
  effective_refund_usd       = LEAST(refunds_usd, gross_revenue_usd)   -- capped at order-total gross
  net_revenue_usd            = gross_revenue_usd − effective_refund_usd -- floored at 0
  revenue_usd                = net_revenue_usd   -- alias; downstream reads NET
  cogs_usd                   = fact_order_cost.cogs_usd
  design_fee_usd              = fact_order_cost.design_fee_usd
  payment_fee_usd             = coalesce(fact_order.payment_fee_usd, fact_order_cost.payment_fee_fallback_usd, 0)
  contribution_profit_usd     = net_revenue_usd − cogs_usd − design_fee_usd − payment_fee_usd
  profit_margin               = contribution_profit_usd / nullif(net_revenue_usd, 0)   -- NULL when fully refunded
  cost_confidence             = fact_order_cost.cost_confidence
  cost_allocation_method      = fact_order_cost.cost_allocation_method
  payment_fee_source          = fact_order.payment_fee_source
```

Scope: an order is in `mart_order_profit` only when it has cost enrichment AND `gross_product_revenue_usd > 0` (pre-refund) — an order whose lines are all failed/cancelled/pending never enters (so its shipping is never counted as phantom revenue either). A **fully refunded** order stays in scope (it did sell) with `net_revenue_usd` floored at zero (not negative), so it correctly shows a COGS loss rather than being dropped.

### 4.3 Product-level profit (`mart_product_profit`)

COGS may be available **only at order level** in the sheet. Allocate to lines:

| Method | When applied | `cost_allocation_method` | `cost_confidence` |
|---|---|---|---|
| Line-exact | Sheet records per-line cost | `'line_exact'` | `1.00` |
| Allocated by revenue share | Default fallback when only order-level cost exists | `'allocated_by_revenue_share'` | `0.60` |
| Allocated by quantity share | Opt-in alternative | `'allocated_by_quantity_share'` | `0.50` |

For revenue-share allocation, EVERY order-level term (customer shipping revenue, COGS, design fee, payment fee, and the capped `effective_refund_usd`) is allocated to lines by the same share:
```
line_<term>_usd = order.<term>_usd * (line.line_revenue_usd / order.revenue_usd)
line_net_revenue_usd = line.line_revenue_usd + line_shipping_usd − line_refund_usd
line_profit_usd       = line_net_revenue_usd − line_cogs_usd − line_design_fee_usd − line_payment_fee_usd
```
`line_revenue_usd` itself stays product-only (never mutated); the allocated shipping is a separate `line_shipping_usd` column. `SUM(line_profit_usd)` across all lines of an order equals `mart_order_profit.contribution_profit_usd` exactly (to the cent; verified $86,670.64 = $86,670.64 on real FOS data, post-cleanup 2026-07-23).

Every product-profit row carries `cost_allocation_method` and `cost_confidence`. Dashboards displaying product-level profit show a caveat tag whenever `cost_allocation_method != 'line_exact'`.

### 4.4 What is *not* used for profit
- CSV's `Revenue`, `Profit`, `ROI`, `Profit Margin` — drift-monitored in `marts_recon.recon_csv_vs_dbt_*`, never official.
- CSV `Shipping` — the CSV copy of the customer shipping charge; used only for the like-for-like shipping recon. The **official** customer shipping charge is Woo's `fact_order.shipping_charged_usd`, which **is** revenue in the profit base (§4.1). Shipping is added on the revenue side, never subtracted as a cost.
- A separate supplier shipping cost — does not exist as a distinct field today (it's inside COGS).

---

## 5. Dimensions

### 5.1 `dim_date`
2020-01-01 → 2030-12-31, generated by `dbt_utils.date_spine`.

### 5.2 `dim_site`
From seed `dbt/seeds/dim_site_seed.csv`.
```
site_sk          INT PK
site_code        TEXT UNIQUE
site_name        TEXT
domain           TEXT
default_currency TEXT
timezone         TEXT     -- source WordPress/WooCommerce site timezone
reporting_timezone TEXT  -- business/dashboard timezone
is_active        BOOL
```

### 5.3 `dim_product`
Sourced from `raw.woo_products` + `raw.woo_orders.line_items.meta_data` per the **Phase 1 payload audit**.
```
product_sk        INT PK
site_sk           INT FK
woo_product_id    INT
woo_variation_id  INT NULL
product_name      TEXT
product_url       TEXT
product_type      TEXT   -- audit-confirmed
gender_target     TEXT   -- audit-confirmed
size              TEXT   -- audit-confirmed
color             TEXT   -- audit-confirmed if present
design_topic      TEXT
first_seen_date   DATE
last_seen_date    DATE
```

### 5.4 `dim_customer_anonymized`
**Never carries plaintext PII. Never carries aggregate behavior** — those live in `mart_customer_summary`.
```
customer_sk        INT PK
customer_hash      TEXT     -- SHA-256(lower(trim(email)) || PII_SALT) or 'unknown:<site>:<woo_order_id>'
is_unknown_email   BOOL
country_sk         INT FK   -- billing country at first seen
first_order_date   DATE
last_order_date    DATE
```

### 5.5 `dim_country`
```
country_sk    INT PK
country_code  TEXT     -- ISO 3166-1 alpha-2
country_name  TEXT
region        TEXT
currency      TEXT
```

### 5.6 `dim_channel` (Phase 6)
From GA4 + (optional) ads UTM.
```
channel_sk        INT PK
source            TEXT
medium            TEXT
campaign          TEXT
channel_grouping  TEXT
is_paid           BOOL
```

### 5.7 `dim_supplier` (Phase 5)
From seed + CSV enrichment.
```
supplier_sk       INT PK
supplier_name     TEXT
supplier_store_id TEXT
sla_days          INT
```

### 5.8 `dim_device` (Phase 6)
```
device_sk        INT PK
device_category  TEXT
operating_system TEXT
browser          TEXT
```

### 5.9 `dim_page` (Phase 6)
```
page_sk            INT PK
page_path          TEXT
page_type          TEXT
is_landing_eligible BOOL
```

### 5.10 `dim_payment_method`
From Woo `payment_method`.
```
payment_method_sk INT PK
method_code       TEXT
method_name       TEXT
```

---

## 6. Fact Tables

### 6.1 `fact_order` — Woo order header (no revenue)

```
order_sk                INT PK
site_sk                 INT FK
date_sk                 INT FK
customer_sk             INT FK
country_sk              INT FK
payment_method_sk       INT FK
order_natural_key       TEXT   -- site_code || '-' || woo_order_id
woo_order_id            INT
status                  TEXT
status_is_cancelled     BOOL
currency_source         TEXT
fx_rate_to_usd          NUMERIC
order_total_src         NUMERIC
order_total_usd         NUMERIC
shipping_charged_src    NUMERIC          -- customer shipping charge, source currency (Woo official)
shipping_charged_usd    NUMERIC          -- customer shipping charge, USD
discount_src            NUMERIC
discount_usd            NUMERIC
tax_src                 NUMERIC
tax_usd                 NUMERIC
payment_fee_usd         NUMERIC NULL     -- per-order payment fee
payment_fee_source      TEXT             -- 'api_exact' | 'plugin_parser' | 'seed_estimate' | 'missing'
payment_fee_needs_review BOOL            -- TRUE when source = 'missing'
order_count             INT              -- always 1
```

**Notes:**
- `shipping_charged_*` is what the customer paid for shipping (revenue-side component). It is **not** a cost.
- The corresponding CSV column (`Shipping`) is the same concept (customer shipping charge), and a reconciliation view `recon_woo_vs_csv_shipping_charged` compares the two. **Woo is official.**

### 6.2 `fact_order_item` — Woo line item (REVENUE LIVES HERE)
```
order_item_sk        BIGINT PK
order_sk             INT FK
site_sk              INT FK
date_sk              INT FK
product_sk           INT FK
woo_line_item_id     INT
quantity             INT
unit_price_src       NUMERIC
line_subtotal_src    NUMERIC
line_total_src       NUMERIC
fx_rate_to_usd       NUMERIC
line_revenue_usd     NUMERIC                -- official revenue
```
(No `cogs` here; cost comes from `fact_order_cost` via allocation in `mart_product_profit`.)

### 6.3 `fact_refund` — Woo refund/cancellation (ORDER-LEVEL by default)
```
refund_sk            BIGINT PK
order_sk             INT FK
order_item_sk        BIGINT FK NULL        -- nullable; only set if audit confirms item-level refund detail
date_sk              INT FK
refund_amount_usd    NUMERIC
refund_reason        TEXT
event_type           TEXT                  -- 'refund' | 'cancellation'
```

Phase 1 default grain: one row per refunded/cancelled Woo order. Item-level rows enabled only if the Phase 1 audit confirms item-level fields are populated.

### 6.4 `fact_order_cost` — manual sheet cost enrichment (Phase 3)

```
order_cost_sk            INT PK
order_sk                 INT FK           -- joined by (site_code, woo_order_id)
site_sk                  INT FK
date_sk                  INT FK
cogs_usd                 NUMERIC NULL     -- includes supplier fulfillment/shipping fee where applicable
design_fee_usd           NUMERIC NULL
payment_fee_fallback_usd NUMERIC NULL     -- only populated if Woo cannot provide an exact value
cost_source              TEXT             -- 'manual_csv' (today); 'supplier_api' (future)
cost_allocation_method   TEXT             -- 'line_exact' | 'allocated_by_revenue_share' | 'allocated_by_quantity_share' | 'order_only'
cost_confidence          NUMERIC          -- 0.00 – 1.00
csv_revenue_observed_usd NUMERIC NULL     -- for drift recon only
csv_profit_observed_usd  NUMERIC NULL     -- for drift recon only
csv_shipping_charged_usd NUMERIC NULL     -- for recon only; the CSV 'Shipping' column = customer shipping charge
```

**Hard rules:**
- `cogs_usd` includes the supplier fulfillment/shipping fee. Do **not** subtract a separate shipping cost in any profit formula.
- `csv_shipping_charged_usd` exists for reconciliation against `fact_order.shipping_charged_usd`. It is **not** a cost.
- There is **no `actual_shipping_cost_usd`** anywhere in the model. (Removed deliberately — that concept does not exist in the data.)

### 6.5 `fact_fulfillment` — manual CSV (Phase 5)
```
fulfillment_sk        INT PK
order_sk              INT FK
supplier_sk           INT FK
ship_date_sk          INT FK NULL
deliver_date_sk       INT FK NULL
shipping_company      TEXT
tracking_id_hash      TEXT
fulfill_url_hash      TEXT
tracking_url_hash     TEXT
fulfillment_days      INT NULL
delivery_days         INT NULL
status                TEXT                -- 'fulfilled','in_transit','delivered','exception'
check_sent            BOOL
note_present          BOOL
```

### 6.6 GA4 facts (Phase 6)
Schemas: `fact_ga4_event`, `fact_ga4_session`, `fact_ga4_pageview`, `fact_ga4_ecommerce_event`. See [PIPELINE_DESIGN.md §4](PIPELINE_DESIGN.md). Activation gated by `docs/GA4_BIGQUERY_AUDIT.md`.

### 6.7 `fact_ad_spend_daily` (Optional Future)
Not part of MVP.

---

## 7. Marts (computed)

### 7.1 `mart_order_profit`
See §4.2.

### 7.2 `mart_product_profit`
See §4.3. Carries `cost_allocation_method` and `cost_confidence`.

### 7.3 `mart_country_profit`
Roll-up of `mart_order_profit` to country × period.

### 7.4 `mart_customer_summary`
```
customer_sk        INT PK
customer_hash      TEXT
first_order_date   DATE
last_order_date    DATE
total_orders       INT
total_revenue_usd  NUMERIC
total_profit_usd   NUMERIC
is_repeat          BOOL
preferred_site_sk  INT
preferred_country_sk INT
```

---

## 8. Relationships (star)

```
                       ┌──────────────┐
                       │  dim_date    │
                       └──────┬───────┘
                              │
   ┌──────────┐               │            ┌──────────────┐
   │ dim_site ├───┐           │        ┌───┤ dim_product  │
   └──────────┘   │           │        │   └──────────────┘
                  ▼           ▼        ▼
   ┌──────────────────────────────────────────┐
   │ fact_order_item  (REVENUE)               │
   └────────────┬─────────────────────────────┘
                │  rolls up by order_sk
                ▼
   ┌──────────────────────────────────────────┐
   │ fact_order  (shipping_charged_usd /      │──► fact_refund (order-level)
   │             discount / tax / payment_fee)│
   └────────────┬─────────────────────────────┘
                │  joined by (site_sk, woo_order_id)
                ▼
   ┌──────────────────────────────────────────┐
   │ fact_order_cost     (Phase 3, COGS+fees) │──► mart_order_profit
   │ fact_fulfillment    (Phase 5, supplier)  │      │
   └──────────────────────────────────────────┘      ▼
                                                mart_product_profit
                                                mart_country_profit
                                                mart_customer_summary

   ┌──────────────┐    ┌──────────────┐
   │ dim_channel  ├───►│ fact_ga4_*   │◄──┤ dim_device │   (Phase 6, audit-gated)
   └──────────────┘    └──────┬───────┘    └────────────┘
                              │  transaction_id (gated by GA4_BIGQUERY_AUDIT)
                              ▼
                         fact_order
```

---

## 9. POD-specific considerations

- **Design vs product type:** same design appears across types and genders. `dim_product.design_topic` enables design-level roll-up.
- **Multi-currency at order level:** `*_src` and `*_usd` side by side; FX is per-order via `seeds/fx_rates.csv` (replaceable by FX API).
- **Supplier ≠ Woo order:** a Woo order can have multiple supplier orders. `fact_fulfillment` links at order header.
- **Fees stay split:** payment fee, design fee, and COGS (which includes supplier shipping) — separate columns to keep contribution-margin analysis honest.
- **Refunds may cross periods:** book on refund date, not order date.
- **Customer shipping charge ≠ supplier shipping cost.** Customer charge lives in `fact_order.shipping_charged_usd`; supplier fee is folded into `fact_order_cost.cogs_usd`.

---

## 10. GA4 modeling — event vs session

`fact_ga4_session` is built from `fact_ga4_event` by aggregation over `(user_pseudo_id, ga_session_id)`. See [PIPELINE_DESIGN.md §4](PIPELINE_DESIGN.md).

---

## 11. Joining GA4 to Woo orders — gated by audit

```sql
LEFT JOIN fact_order
  ON fact_ga4_session.transaction_id = fact_order.woo_order_id::text
 AND fact_ga4_session.site_sk        = fact_order.site_sk
```

Activated only when the **Phase 6 transaction_id audit** in [GA4_BIGQUERY_AUDIT.md](GA4_BIGQUERY_AUDIT.md) confirms a high (≥85%) match rate.

---

## 12. Expected reconciliation gaps

| Comparison | Expect | Tracked in |
|---|---|---|
| GA4 `purchase` count vs `fact_order` count per day | GA4 ~5–25% lower | `recon_ga4_vs_woo_daily` |
| GA4 `purchase_revenue` vs `fact_order_item.line_revenue_usd` | Drifts | same |
| CSV `Revenue` vs `fact_order_item.line_revenue_usd` | Tracked, never official | `recon_csv_vs_dbt_revenue` |
| CSV `Profit` vs `mart_order_profit.contribution_profit_usd` | Tracked, informational | `recon_csv_vs_dbt_profit` |
| CSV `Shipping` vs `fact_order.shipping_charged_usd` | Tracked | `recon_woo_vs_csv_shipping_charged` |
| % Woo orders with `fact_order_cost` | Target ≥80% (gating tiers in METRICS §J) | `recon_cost_coverage` |
| % Woo orders with `fact_fulfillment` | Target ≥80% | `recon_fulfillment_coverage` |

---

## 13. Source-of-Truth Mapping (final reference)

| Mart / fact | System of record |
|---|---|
| `dim_site` | Seed `dim_site_seed.csv` |
| `dim_product` | WooCommerce + audit-confirmed `meta_data` parsing |
| `dim_customer_anonymized` | WooCommerce billing email (hashed) |
| `dim_country` | Seed `country_iso_map.csv` |
| `dim_payment_method` | WooCommerce `payment_method` |
| `dim_channel` | GA4 + (optional) ads UTM |
| `dim_supplier` | Seed + manual CSV |
| `dim_device`, `dim_page` | GA4 |
| `fact_order` (incl. `shipping_charged_*`) | WooCommerce |
| `fact_order_item` (revenue) | WooCommerce |
| `fact_refund` | WooCommerce |
| `fact_order_cost` (`cogs_usd` includes supplier shipping) | **Manual Order Management CSV** |
| `fact_fulfillment` | Manual CSV (later Printify + carrier APIs) |
| `mart_*` (profit, customer summary) | dbt-computed |
| `fact_ga4_*` | GA4 |
| `fact_ad_spend_daily` | Ads (Optional Future) |

The CSV's `Revenue` / `Profit` / `ROI` / `Profit Margin` / `Shipping` columns are **never** copied as official metrics. They appear in `marts_recon.recon_csv_vs_dbt_*` and `recon_woo_vs_csv_shipping_charged` only.

---

## 14. Naming conventions

- snake_case throughout.
- Surrogate keys: `<table>_sk` (bigint for high-volume facts).
- Natural keys for Woo entities: include both `site_code` and `woo_<entity>_id`.
- Money: always with unit (`_usd`, `_src`).
- Customer shipping charge: `shipping_charged_*` (Woo official) and `csv_shipping_charged_usd` (CSV recon).
- Raw timestamps preserve WooCommerce source date fields; extraction watermarks prefer GMT/UTC fields such as `date_modified_gmt`.
- Timestamps are UTC unless suffixed `_local`. Marts may expose both source site-local dates and reporting dates derived from `dim_site.reporting_timezone`.
- Booleans: `is_*`, `has_*`, `*_needs_review`.
- Payment fee source enum: `'api_exact' | 'plugin_parser' | 'seed_estimate' | 'missing'`.
