# Pipeline Design

> Python handles extract/load to `raw`. dbt handles `raw → staging → marts`. Four extract/load pipelines feed one dbt transformation graph. Ads is **Optional Future**, not part of MVP. Manual CSV is **private-only, gitignored, never exported, never used in the public sample**.

---

## 1. Architectural Split

```
┌─────────────┐      ┌─────────────┐      ┌──────────────┐
│  Sources    │ ───► │ Python EL   │ ───► │ Postgres raw │
└─────────────┘      └─────────────┘      └──────┬───────┘
                                                 │
                                          ┌──────▼───────┐
                                          │   dbt        │
                                          │  raw → stg → │
                                          │  marts       │
                                          └──────┬───────┘
                                                 ▼
                                            Power BI
```

- **Python** never applies business logic. Pulls, lands, logs.
- **dbt** owns every business transformation: typing, FX, hashing, joining, cost allocation, profit calculation, building marts, running tests, generating docs.

---

## 2. Layering & Naming

| Schema | Owner | Purpose |
|---|---|---|
| `raw` | Python ELT | Exact source copy, append-only, with `extracted_at` and `_payload` JSON |
| `staging` | dbt | Cleaned, typed, deduped, PII hashed |
| `marts_core` | dbt | dim_* + sales/order/customer facts + profit marts |
| `marts_marketing` | dbt | GA4 facts and (optional) ads facts |
| `marts_operations` | dbt | `fact_order_cost`, `fact_fulfillment`, supplier |
| `marts_recon` | dbt | Cross-source reconciliation |

**Table naming:**
- `raw.<source>_<entity>` — e.g. `raw.woo_orders`, `raw.ga4_events`, `raw.csv_order_management`
- `staging.stg_<source>_<entity>` — e.g. `stg_woo_orders`, `stg_manual_order_cost_enrichment`
- Marts: `dim_*`, `fact_*`, `mart_*`

Multi-site: every raw/staging/mart row carries `site_code` and/or `site_sk`. Order natural key = `site_code + woo_order_id`.

---

## 3. WooCommerce Pipeline (Phase 1)

For each site in `config/sites.yaml`:

```
WooCommerce REST API
  /orders?modified_after=<watermark>&per_page=100
  /orders/<id>/refunds
  /products, /customers, /coupons
        │
        ▼ (paginate)
[Python httpx, basic auth with consumer key/secret per site]
        │
        ▼
raw.woo_orders (with line_items in _payload),
raw.woo_order_items,
raw.woo_products, raw.woo_customers, raw.woo_refunds, raw.woo_coupons
        │  every row: site_code, extracted_at, _payload JSONB
        │
        ▼
[Phase 1 payload audit → docs/WOO_PAYLOAD_AUDIT.md]
        │
        ▼
[dbt staging] stg_woo_orders (incl. shipping_charged_*),
              stg_woo_order_items (variant parsing wired to audit),
              stg_woo_products,
              stg_woo_customers (PII hashed),
              stg_woo_refunds (order-level grain),
              stg_woo_coupons
        │
        ▼
[dbt marts_core] dim_product, dim_customer_anonymized, dim_country,
                 dim_payment_method, fact_order, fact_order_item, fact_refund,
                 mart_customer_summary
```

**Key design points:**
- High-watermark incremental on `date_modified_gmt`, persisted in `raw.pipeline_state`.
- Preserve raw WooCommerce date fields as provided; prefer GMT/UTC fields for extraction watermarks.
- Site `timezone` is the source WordPress/WooCommerce timezone. `reporting_timezone` is the business/dashboard timezone; marts can expose both site-local date and reporting date. For FOS, source `timezone` is UTC; do not use `Europe/London` because London observes daylight saving time and may become UTC+1.
- Idempotent upsert on `(site_code, woo_<entity>_id)`.
- Site isolation: separate consumer key per site; loop sequentially.
- Rate limit safety: exponential backoff on 429/5xx.
- JSON safety net: full payload retained in `_payload` JSONB.
- Watermark advances only on full-pagination success.
- **Payment fee parser** is plugin-specific; the parser path is locked in `docs/WOO_PAYLOAD_AUDIT.md`. `payment_fee_source` on `fact_order` is set to one of `'api_exact' | 'plugin_parser' | 'seed_estimate' | 'missing'`.
- **Variant parser** is audit-driven; pulls only from `meta_data` keys confirmed by `WOO_PAYLOAD_AUDIT.md`.
- **Refund grain** is order-level by default; item-level is enabled only if the audit confirms item-level fields.
- **Customer shipping charge:** `stg_woo_orders` maps the Woo shipping total field (confirmed via audit) to `shipping_charged_src` / `shipping_charged_usd`.

---

## 4. GA4 BigQuery Pipeline (Phase 6, audit-gated)

### 4.1 Source
- Project: `<your-gcp-project>`
- Dataset: `analytics_<property_id>` per site
- Daily: `events_YYYYMMDD`; intraday: `events_intraday_YYYYMMDD`

### 4.2 Auth
- Service account JSON path in `.env` as `GOOGLE_APPLICATION_CREDENTIALS`.

### 4.3 Audit gate (must complete before attribution is enabled)
See [GA4_BIGQUERY_AUDIT.md](GA4_BIGQUERY_AUDIT.md). Decision (≥85% match → attribution active; <85% → behavior only) is recorded there.

### 4.4 Daily extract logic
```
For each GA4 property (per site):
    For each date D in [last_loaded+1 .. yesterday]:
        If events_YYYYMMDD exists:
            extract → Parquet under data/raw/ga4/site=<code>/date=<D>/
            load to raw.ga4_events (partitioned by event_date, site_code)
            mark D in raw.pipeline_state
        Else skip, retry next run.
```

Optional intraday refresh of `events_intraday_YYYYMMDD` → `raw.ga4_events_intraday`.

### 4.5 dbt models
- `stg_ga4_events`
- `stg_ga4_sessions` — aggregate over `(user_pseudo_id, ga_session_id)`
- `stg_ga4_ecommerce_events` — `UNNEST(items)`
- `fact_ga4_event`, `fact_ga4_session`, `fact_ga4_pageview`, `fact_ga4_ecommerce_event` in `marts_marketing`
- `marts_recon.recon_ga4_vs_woo_daily`

### 4.6 GA4 ↔ Woo join (gated)
```sql
LEFT JOIN fact_order
  ON fact_ga4_session.transaction_id = fact_order.woo_order_id::text
 AND fact_ga4_session.site_sk = fact_order.site_sk
```
Suppressed when the audit gate fails.

---

## 5. Manual Order Management Pipeline (Phases 3 & 5)

> **Privacy rule:** `raw.csv_order_management` is **private-only, local-only, gitignored, never exported, and never used in the public sample**. The public portfolio uses fully synthetic data only.
>
> **Manual CSV PII rule:** for the manual Order Management CSV, unnecessary PII columns such as `Name`, `Email`, `Phone`, and `Ship to` are dropped **before** loading into `raw.csv_order_management`. Therefore `raw.csv_order_management` is **not** a byte-for-byte copy of the full sheet; it is a private raw operational extract with PII removed at ingestion. Tracking IDs and fulfillment URLs may be loaded to raw but **must** be hashed before staging/marts.

### 5.1 Source
- `Order Management.csv` exported from the Google Sheet; later may be replaced by direct Sheet API access.

### 5.2 Extract (Python)
`src/extract/csv_order_management.py`:
- `pd.read_csv(skiprows=[1,2])`
- Drop PII at load (`Name`, `Email`, `Phone`, `Ship to`)
- Normalize column names (strip whitespace, ASCII-fold `Típs/Coupon`)
- Derive `(site_code, woo_order_id)` join keys from `Project` + `Order Code`
- Forward-fill order-level fields onto child rows
- Upsert into `raw.csv_order_management` with `extracted_at`

### 5.3 Staging — split into two enrichment models

**`stg_manual_order_cost_enrichment`** (Phase 3, cost):

Output columns:
```
site_code
woo_order_id
cogs_usd                         -- includes supplier fulfillment/shipping fee where applicable
design_fee_usd
payment_fee_fallback_usd         -- only populated when Woo cannot provide an exact value
csv_revenue_observed_usd         -- recon only
csv_profit_observed_usd          -- recon only
csv_shipping_charged_usd         -- recon only; the CSV 'Shipping' column = customer shipping charge
cost_source                      -- 'manual_csv' (today); 'supplier_api' (future)
cost_allocation_method
cost_confidence
```

**Important:**
- The CSV `Shipping` column is the **customer shipping charge** (revenue-side) — *not* supplier shipping cost. Loaded for reconciliation only.
- WooCommerce shipping (from `fact_order.shipping_charged_usd`) is the official customer shipping charge if present. `recon_woo_vs_csv_shipping_charged` compares them.
- CSV `Shipping` is **not** treated as a supplier cost anywhere in the pipeline.
- Supplier fulfillment/shipping fee is already inside `cogs_usd`. There is no `actual_shipping_cost_usd` column.

**`stg_manual_fulfillment_enrichment`** (Phase 5, fulfillment):

Output columns:
```
site_code
woo_order_id
supplier_store_id        -- parsed from #<store>.<order>
supplier_order_id
fulfill_url_hash
tracking_id_hash
tracking_url_hash
shipping_company
check_sent
note_present
```

### 5.4 Marts
- `marts_operations.fact_order_cost` (Phase 3) — order-level; carries `cost_source`, `cost_allocation_method`, `cost_confidence`. No `actual_shipping_cost_usd`.
- `marts_operations.fact_fulfillment` (Phase 5)
- `marts_core.mart_order_profit`, `mart_product_profit` (Phase 3+). Each carries conformed FKs (`country_sk`, `customer_sk`, `payment_method_sk` + degenerate `order_status`) inherited from `fact_order` so any dim slices them directly (see [DATA_MODEL.md §1/§8](DATA_MODEL.md) and `DATA_MODEL_REDESIGN_SPEC.md`, 2026-07-24). *(`mart_country_profit` removed — country reads `mart_order_profit` directly.)*

Contribution profit formula (locked in [DATA_MODEL.md §4.1](DATA_MODEL.md)):
```
contribution_profit_usd = revenue_usd − cogs_usd − design_fee_usd − payment_fee_usd
```

### 5.5 Reconciliation & coverage models
- `marts_recon.recon_csv_vs_dbt_revenue` — CSV `Revenue` vs `fact_order_item.line_revenue_usd`
- `marts_recon.recon_csv_vs_dbt_profit` — CSV `Profit` vs `mart_order_profit.contribution_profit_usd`
- `marts_recon.recon_woo_vs_csv_shipping_charged` — Woo `shipping_charged_usd` vs CSV `csv_shipping_charged_usd`
- `marts_recon.recon_cost_coverage` — % Woo orders with `fact_order_cost`, % with non-null `cogs_usd`
- `marts_recon.recon_payment_fee_coverage` — % orders with non-null `payment_fee_usd`, broken out by `payment_fee_source`
- `marts_recon.recon_fulfillment_coverage` — % orders with `fact_fulfillment`

### 5.6 Tests
- `not_null(order_sk)` on `fact_order_cost`, `fact_fulfillment`
- `relationships(order_sk → fact_order)` on both
- `accepted_values('manual_csv','supplier_api')` on `cost_source`
- `accepted_values('api_exact','plugin_parser','seed_estimate','missing')` on `payment_fee_source`
- Singular tests with tiered warnings on cost coverage (see [METRICS_DEFINITION.md §J](METRICS_DEFINITION.md))

### 5.7 Refreshing the warehouse (runbook)

Full refresh cycle, run from the repo root (Windows PowerShell, using the venv
Python). WooCommerce is incremental; the manual CSV is a truncate-reload
snapshot; dbt rebuilds every model + test.

```powershell
# 1. WooCommerce raw ingestion (incremental high-watermark; idempotent upsert)
.\.venv\Scripts\python.exe -m src.extract.woo_api

# 2. Manual cost enrichment (TRUNCATE-and-reload of raw.csv_order_management;
#    reads CSV_ORDER_MANAGEMENT_PATH or data/raw/manual/order_management.csv)
.\.venv\Scripts\python.exe -m src.extract.csv_order_management

# 3. dbt transform + test (raw -> staging -> marts). Run from dbt/ with .env
#    loaded so PII_SALT is present for the hashing macro.
dbt build
```

Notes:
- Step 2 is a snapshot: rows deleted from the sheet disappear from raw on the
  next run (unlike the incremental Woo upsert). Pass `--apply-ddl` the first
  time to create `raw.csv_order_management`.
- Cost coverage and payment-fee coverage are surfaced by
  `marts_recon.recon_cost_coverage` / `recon_payment_fee_coverage`; the singular
  tests `assert_cost_coverage_tiers` and `assert_payment_fee_coverage_at_least_80`
  **warn** (never error) when below their thresholds — low coverage is a
  data-completeness signal, not a pipeline failure.

---

## 6. Ads Pipeline (Optional Future)

Not part of MVP. Activated only if ads ever run. `dbt/seeds/utm_campaign_map.csv` maps campaign names to UTM `campaign`.

---

## 7. dbt Project Layout

```
dbt/
├── dbt_project.yml
├── profiles.yml                        # gitignored copy at ~/.dbt/
├── packages.yml                        # dbt_utils, dbt_expectations
├── models/
│   ├── staging/
│   │   ├── woocommerce/
│   │   │   ├── _sources.yml
│   │   │   ├── stg_woo_orders.sql
│   │   │   ├── stg_woo_order_items.sql
│   │   │   ├── stg_woo_products.sql
│   │   │   ├── stg_woo_customers.sql
│   │   │   ├── stg_woo_refunds.sql
│   │   │   └── stg_woo_coupons.sql
│   │   ├── ga4/
│   │   │   ├── _sources.yml
│   │   │   ├── stg_ga4_events.sql
│   │   │   ├── stg_ga4_sessions.sql
│   │   │   └── stg_ga4_ecommerce_events.sql
│   │   └── manual/
│   │       ├── _sources.yml
│   │       ├── stg_manual_order_cost_enrichment.sql
│   │       └── stg_manual_fulfillment_enrichment.sql
│   ├── marts/
│   │   ├── core/
│   │   │   ├── dim_date.sql
│   │   │   ├── dim_site.sql
│   │   │   ├── dim_product.sql
│   │   │   ├── dim_customer_anonymized.sql
│   │   │   ├── dim_country.sql
│   │   │   ├── dim_payment_method.sql
│   │   │   ├── fact_order.sql
│   │   │   ├── fact_order_item.sql
│   │   │   ├── fact_refund.sql
│   │   │   ├── mart_order_profit.sql
│   │   │   ├── mart_product_profit.sql
│   │   │   └── mart_customer_summary.sql
│   │   ├── marketing/
│   │   │   ├── dim_channel.sql
│   │   │   ├── dim_device.sql
│   │   │   ├── dim_page.sql
│   │   │   ├── fact_ga4_event.sql
│   │   │   ├── fact_ga4_session.sql
│   │   │   ├── fact_ga4_pageview.sql
│   │   │   ├── fact_ga4_ecommerce_event.sql
│   │   │   └── fact_ad_spend_daily.sql        # optional future
│   │   ├── operations/
│   │   │   ├── dim_supplier.sql
│   │   │   ├── fact_order_cost.sql
│   │   │   └── fact_fulfillment.sql
│   │   └── reconciliation/
│   │       ├── recon_csv_vs_dbt_revenue.sql
│   │       ├── recon_csv_vs_dbt_profit.sql
│   │       ├── recon_woo_vs_csv_shipping_charged.sql
│   │       ├── recon_cost_coverage.sql
│   │       ├── recon_payment_fee_coverage.sql
│   │       ├── recon_fulfillment_coverage.sql
│   │       └── recon_ga4_vs_woo_daily.sql
│   └── schema.yml
├── seeds/
│   ├── dim_site_seed.csv
│   ├── dim_supplier_seed.csv
│   ├── country_iso_map.csv
│   ├── fx_rates.csv
│   ├── payment_fees.csv                       # fallback only (`seed_estimate`)
│   ├── product_cogs.csv                       # legacy fallback only
│   └── utm_campaign_map.csv                   # optional future
├── snapshots/
├── macros/
│   └── hash_pii.sql
└── tests/
    └── singular/
        ├── assert_cost_coverage_tiers.sql           # warns at <80% and <95% per §J
        ├── assert_payment_fee_coverage_at_least_80.sql
        └── assert_fulfillment_coverage_at_least_80.sql
```

---

## 8. dbt Tests

**Generic (`schema.yml`):**
- `unique` on every PK
- `not_null` on FKs and money columns
- `accepted_values` on `status`, `currency`, `event_name`, `cost_allocation_method`, `cost_source`, `payment_fee_source`
- `relationships` between every fact and its dim

**Custom (dbt_utils / dbt_expectations):**
- `expression_is_true: line_revenue_usd >= 0`
- `expression_is_true: quantity > 0`
- `expression_is_true: cost_confidence BETWEEN 0 AND 1`
- `equal_rowcount` between `stg_woo_orders` and dedup of `raw.woo_orders`

**Singular tests:** coverage thresholds (warn) and reconciliation drift thresholds (warn). Cost coverage uses tiered thresholds (<80% / 80–95% / ≥95%).

---

## 9. Cross-cutting

### 9.1 Logging
- Each EL run writes `raw.pipeline_runs(run_id, pipeline_name, site_code, start_ts, end_ts, status, rows_in, rows_out, error_text)`.

### 9.2 Retries & failures
- HTTP: exponential backoff, max 5 retries.
- BigQuery: abort on quota; retry next run.
- Malformed CSV row: write to `quarantine_<entity>.csv`; continue.

### 9.3 Data quality checks
| Check | Action |
|---|---|
| No nulls in PKs | dbt `not_null` → fail |
| No duplicates | dbt `unique` → fail |
| Currency in known set | `accepted_values` → fail |
| `line_revenue_usd >= 0` | `expression_is_true` → fail |
| Cost coverage < 80% | singular → **warn** + dashboard hides profit |
| Cost coverage 80–95% | singular → **info** + dashboard chips |
| Payment fee coverage < 80% | singular → **warn** |
| Fulfillment coverage < 80% (Phase 5) | singular → **warn** |
| GA4 transaction_id match < 85% | singular → **warn** (attribution gate) |
| CSV vs Woo revenue delta > 5% | singular → **warn** |
| CSV vs Woo shipping charged delta > 5% | singular → **warn** |

### 9.4 Schema evolution
- New WooCommerce fields appear inside `raw.woo_*._payload`.
- Staging models must explicitly select them; silent ignoring is the default.

### 9.5 Privacy (cross-pipeline)
- `raw.csv_order_management`, `raw.woo_customers`, `raw.woo_orders.billing/shipping`, GA4 raw user identifiers — **all private-only, local-only, gitignored**.
- PII must never cross the `raw → staging` boundary unhashed.
- The public portfolio dataset is fully synthetic; no row in it derives from real customer data.

---

## 10. Scheduling Options

| Tool | When |
|---|---|
| Manual `make load && dbt build` | Phase 1–4 |
| Task Scheduler / cron | Phase 5–6 |
| GitHub Actions cron | Phase 6+ |
| Prefect / Airflow / Dagster | only when ≥3 schedules exist |

---

## 11. Secrets Management

- All credentials in `.env`, read via `python-dotenv`.
- `.env.example` committed.
- BigQuery JSON via `GOOGLE_APPLICATION_CREDENTIALS`.
- WooCommerce keys: `WOO_<SITECODE>_KEY` / `WOO_<SITECODE>_SECRET`.
- PII salt: `PII_SALT` — generated once, shared with dbt via `env_var('PII_SALT')`. **Back it up offline** — losing it breaks customer linkage.

---

## 12. Python Directory Layout

```
src/
├── extract/
│   ├── woo_api.py                # Phase 1
│   ├── csv_order_management.py   # Phase 3 + 5
│   ├── ga4_bigquery.py           # Phase 6
│   └── ads_<platform>.py         # Optional Future
├── load/
│   ├── db.py
│   └── upsert.py
├── utils/
│   ├── http.py
│   ├── hashing.py
│   ├── ids.py
│   └── logging.py
└── cli.py
```
