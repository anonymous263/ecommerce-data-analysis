# Tasks — Ecommerce Data Analysis (Revised: cost enrichment before profit; ads optional)

> Step-by-step checklist. Each box is small enough to finish in one sitting. Cost enrichment lives in Phase 3 — before the Power BI MVP — because COGS only exists in the manual sheet.

---

## Phase 0 — Setup, Privacy, and Source Audit

### Repo & environment
- [x] `git init`
- [x] Create GitHub repo (private at first)
- [x] Write strict `.gitignore`: `.env`, `data/raw/`, `Order Management.csv`, `dbt/target/`, `dbt/dbt_packages/`, `__pycache__/`, `.venv/`, `*.pbix.backup`
- [x] Confirm `Order Management.csv` does NOT appear in `git status`
- [x] Create Python venv; install base deps (`pandas polars sqlalchemy psycopg2-binary httpx python-dotenv pyarrow jupyterlab pytest dbt-core dbt-postgres`)
- [x] `pip freeze > requirements.txt`
- [x] Generate `PII_SALT` (e.g. `python -c "import secrets; print(secrets.token_hex(32))"`); add to `.env`
- [x] Write `.env.example` with placeholders for `POSTGRES_*`, `WOO_<SITE>_KEY`/`_SECRET`, `PII_SALT`, `GOOGLE_APPLICATION_CREDENTIALS`

### Postgres + dbt
- [x] Write `docker-compose.yml` (Postgres 16)
- [x] `docker compose up -d postgres`
- [x] Create schemas `raw`, `staging`, `marts_core`, `marts_marketing`, `marts_operations`, `marts_recon`
- [ ] `dbt init` in `dbt/`
- [ ] Configure `~/.dbt/profiles.yml`
- [x] Configure `dbt/dbt_project.yml` (per-folder materializations)
- [x] `dbt/packages.yml` with `dbt-labs/dbt_utils` + `calogica/dbt_expectations`
- [ ] `dbt deps && dbt debug` (both must pass)

### Multi-site config
- [x] Create `config/sites.yaml` listing site `FOS` (multi-currency: USD/GBP/CAD/EUR), plus any others
- [x] Create `dbt/seeds/dim_site_seed.csv` mirroring the same site list
- [ ] Add a singular dbt test asserting site list matches between yaml and seed

### Source audit
- [ ] Open `[Đọc cái này trước] Tài liệu Data Dictionary.docx` → save translated summary to `docs/MAVEN_DATA_DICTIONARY.md`
- [ ] Fill `dbt/seeds/dim_supplier_seed.csv` with Printify SLA where known
- [x] Fill `dbt/seeds/country_iso_map.csv` (`UK → GB`, etc.)
- [x] Fill `dbt/seeds/fx_rates.csv` (`date, currency, usd_rate`) — static seed initially (replaceable by FX API later)
- [x] Add `dbt/seeds/payment_fees.csv` placeholder (fallback only)
- [ ] `dbt seed`

### WooCommerce credentials
- [ ] Generate read-only consumer key/secret per site
- [ ] Store as `WOO_<SITECODE>_KEY` / `WOO_<SITECODE>_SECRET` in `.env`
- [ ] Verify with `curl 'https://<domain>/wp-json/wc/v3/orders?per_page=1' -u <key>:<secret>`

---

## Phase 1 — WooCommerce API Raw Ingestion + Payload Audit

### Helpers
- [ ] `src/utils/http.py` (httpx + exponential backoff)
- [ ] `src/utils/logging.py`
- [ ] `src/load/db.py` (SQLAlchemy engine factory)
- [ ] `src/load/upsert.py` (idempotent UPSERT on `(site_code, woo_<entity>_id)`)

### Raw DDL
- [ ] `sql/ddl/01_raw_woo.sql`: `raw.woo_orders`, `raw.woo_order_items`, `raw.woo_products`, `raw.woo_customers`, `raw.woo_refunds`, `raw.woo_coupons`, `raw.pipeline_state`, `raw.pipeline_runs`
- [ ] Each carries `site_code`, `extracted_at`, `_payload JSONB`, PK on `(site_code, woo_<entity>_id)`

### Extractor
- [ ] `src/extract/woo_api.py`:
  - [ ] paginate orders with `modified_after=<watermark>`
  - [ ] for each order fetch `/refunds`
  - [ ] paginate products, customers, coupons
  - [ ] upsert idempotently
  - [ ] update watermark only on success
  - [ ] log to `raw.pipeline_runs`
- [ ] `tests/test_woo_api.py` with mocked payloads (idempotency)
- [ ] `pytest -q` passes
- [ ] Backfill site `FOS`
- [ ] Re-run extractor → no duplicates, row count unchanged
- [ ] Reconcile `raw.woo_orders` row count vs WP admin (≤0.1%)

### Payload Audit — `docs/WOO_PAYLOAD_AUDIT.md`
- [ ] Pull 20 recent orders per active site to `data/raw/audit/<site_code>/orders_sample.json` (gitignored)
- [ ] Fill order-level fields table
- [ ] Fill `line_items[]` fields table
- [ ] Document Acowebs `meta_data` keys (size, type, color, addons)
- [ ] Document whether product_type / gender / size can be parsed automatically
- [ ] Document custom order statuses
- [ ] Document payment fee field location (`meta_data` / `fee_lines` / absent)
- [ ] Document refund fields and confirm grain (order-level confirmed?)
- [ ] Write summary + dbt staging implications
- [ ] Commit + push

---

## Phase 2 — dbt Staging + Core Marts

### Sources
- [ ] `dbt/models/staging/woocommerce/_sources.yml` for all `raw.woo_*`
- [ ] Source `not_null`/`unique` tests

### Macros
- [ ] `dbt/macros/hash_pii.sql` — SHA-256 + `env_var('PII_SALT')`

### Staging models
- [ ] `stg_woo_orders.sql` — parse status, currency, per-order FX→USD via seed, drop PII, **map Woo shipping field → `shipping_charged_src/usd`** (per Phase 1 audit), set `payment_fee_usd` + `payment_fee_source` (`api_exact`/`plugin_parser`/`seed_estimate`/`missing`)
- [ ] `stg_woo_order_items.sql` — unnest, attach `site_sk`, **wire Acowebs variant parsing** per `WOO_PAYLOAD_AUDIT.md`
- [ ] `stg_woo_products.sql`
- [ ] `stg_woo_customers.sql` — hash email; drop names/phones/addresses
- [ ] `stg_woo_refunds.sql` — order-level grain by default; `order_item_sk` nullable
- [ ] `stg_woo_coupons.sql`

### Mart models (core)
- [ ] `marts/core/dim_date.sql`
- [ ] `marts/core/dim_site.sql` (from seed)
- [ ] `marts/core/dim_country.sql`
- [ ] `marts/core/dim_product.sql`
- [ ] `marts/core/dim_customer_anonymized.sql` (no aggregate fields)
- [ ] `marts/core/dim_payment_method.sql`
- [ ] `marts/core/fact_order.sql` — header amounts only (no `revenue_usd`); includes `shipping_charged_src/usd`, `payment_fee_usd`, `payment_fee_source`
- [ ] `marts/core/fact_order_item.sql` — official revenue
- [ ] `marts/core/fact_refund.sql` — order-level grain
- [ ] `marts/core/mart_customer_summary.sql`

### Tests
- [ ] Author `dbt/models/schema.yml`:
  - [ ] `unique` + `not_null` on PKs
  - [ ] `relationships` FK → dim
  - [ ] `accepted_values` on status, currency
  - [ ] `expression_is_true: line_revenue_usd >= 0`
  - [ ] `expression_is_true: quantity > 0`
- [ ] `dbt build` green

### Verify & commit
- [ ] Hand-calc 5 orders' Woo revenue → match `fact_order_item`
- [ ] `dbt docs generate && dbt docs serve` — verify lineage
- [ ] Commit + push

---

## Phase 3 — Manual Cost Enrichment

### Extract

> **Manual CSV PII rule:** for the manual Order Management CSV, unnecessary PII columns such as `Name`, `Email`, `Phone`, and `Ship to` are dropped **before** loading into `raw.csv_order_management`. Therefore `raw.csv_order_management` is **not** a byte-for-byte copy of the full sheet; it is a private raw operational extract with PII removed at ingestion. Tracking IDs and fulfillment URLs may be loaded to raw but **must** be hashed before staging/marts.

- [ ] `src/extract/csv_order_management.py`:
  - [ ] `pd.read_csv(skiprows=[1,2])`
  - [ ] **drop PII (`Name`, `Email`, `Phone`, `Ship to`) BEFORE writing to `raw.csv_order_management`** — raw is not a full copy of the sheet
  - [ ] normalize column names (whitespace, ASCII-fold diacritics)
  - [ ] derive `(site_code, woo_order_id)` from `Project` + `Order Code`
  - [ ] forward-fill order-level fields
  - [ ] upsert into `raw.csv_order_management` with `extracted_at`
  - [ ] keep `Tracking ID`, `Tracking Deliver URL`, `Fulfill URL` raw at this stage (hashed in staging, not at load)
- [ ] `tests/test_csv_order_management.py` — header skip + PII drop (`Name`/`Email`/`Phone`/`Ship to` absent from raw output)

### dbt staging
- [ ] `dbt/models/staging/manual/_sources.yml`
- [ ] `stg_manual_order_cost_enrichment.sql` — outputs:
  - `cogs_usd` (includes supplier fulfillment/shipping fee)
  - `design_fee_usd`
  - `payment_fee_fallback_usd` (only used when Woo cannot provide exact value)
  - `csv_revenue_observed_usd` (recon only)
  - `csv_profit_observed_usd` (recon only)
  - **`csv_shipping_charged_usd`** (recon only — the CSV `Shipping` column is the *customer shipping charge*, NOT supplier cost)
  - `cost_source`, `cost_allocation_method`, `cost_confidence`
  - **Drops** CSV Revenue/Profit/ROI/Profit Margin as official metrics
  - **Does NOT produce** an `actual_shipping_cost_usd` field
- [ ] `stg_manual_fulfillment_enrichment.sql` — parse supplier `#<store>.<order>`; hash tracking ID + URL

### dbt marts
- [ ] `marts/operations/fact_order_cost.sql` — order-level cost with `cost_source`, `cost_allocation_method`, `cost_confidence` (no `actual_shipping_cost_usd`)
- [ ] `marts/core/mart_order_profit.sql` — contribution profit = `revenue_usd − cogs_usd − design_fee_usd − payment_fee_usd` (no shipping subtraction)
- [ ] `marts/core/mart_product_profit.sql` — revenue-share allocation default
- [ ] `marts/core/mart_country_profit.sql`

### Reconciliation
- [ ] `marts/reconciliation/recon_csv_vs_dbt_revenue.sql`
- [ ] `marts/reconciliation/recon_csv_vs_dbt_profit.sql`
- [ ] **`marts/reconciliation/recon_woo_vs_csv_shipping_charged.sql`** — daily delta of Woo `shipping_charged_usd` vs CSV `csv_shipping_charged_usd` per site
- [ ] `marts/reconciliation/recon_cost_coverage.sql`
- [ ] `marts/reconciliation/recon_payment_fee_coverage.sql` — overall % + breakdown by `payment_fee_source`

### Tests
- [ ] `not_null(order_sk)` on `fact_order_cost`
- [ ] `relationships(order_sk → fact_order)` on `fact_order_cost`
- [ ] `accepted_values(cost_allocation_method)` on `fact_order_cost`
- [ ] `accepted_values(cost_source: manual_csv, supplier_api)` on `fact_order_cost`
- [ ] `accepted_values(payment_fee_source: api_exact, plugin_parser, seed_estimate, missing)` on `fact_order`
- [ ] `expression_is_true: cost_confidence BETWEEN 0 AND 1`
- [ ] Singular: `assert_cost_coverage_tiers.sql` — warns at <80% (red) and at <95% (info) per [METRICS_DEFINITION.md §J](docs/METRICS_DEFINITION.md)
- [ ] Singular: `assert_payment_fee_coverage_at_least_80.sql` (warn)
- [ ] `dbt build` green

### Verify
- [ ] Verify whether WooCommerce shipping total matches CSV `Shipping` per order using `recon_woo_vs_csv_shipping_charged` (target daily delta ≤ 5%)
- [ ] Cost coverage tier confirmed (record: red <80% / yellow 80–95% / green ≥95%)
- [ ] CSV revenue vs Woo daily delta ≤ 5%
- [ ] Hand-reconcile 5 sample orders end-to-end (revenue from Woo, cost from CSV, profit from mart, customer shipping charge from Woo)
- [ ] Confirm no `actual_shipping_cost_usd` references remain anywhere in dbt models or DAX
- [ ] Commit + push

---

## Phase 4 — Power BI MVP

### Connect & measures
- [ ] Connect Power BI Desktop to Postgres `marts_core` + `marts_operations`
- [ ] Relationships dim → fact, single direction
- [ ] `_Measures` table
- [ ] Author DAX measures from `METRICS_DEFINITION.md` §A (incl. **A7 Shipping Charged to Customer**, **A8 Shipping Charged/Revenue**), §B (gated), §C, §G (incl. **G4 Shipping Charged Ratio by Country** — labeled "shipping charged to customer / revenue", not cost), §I, §H
- [ ] Implement **tiered profit visibility** per [DASHBOARD_SPEC.md §K](docs/DASHBOARD_SPEC.md):
  - `< 80% Cost Coverage` → hide profit visuals + show "Profit unavailable" banner
  - `80–95%` → show with yellow "Partial cost coverage" chip
  - `≥ 95%` → fully trusted (no chip)
- [ ] Add a second chip whenever **Payment Fee Coverage < 80%**: "Estimated payment fee — XX% from `seed_estimate` or `missing`"
- [ ] Add the profit caveat banner: "COGS includes supplier fulfillment/shipping fee based on the manual sheet, so contribution profit does not subtract shipping again."

### Pages
- [ ] Build **Executive Overview** with tier-gated profit + the Shipping Charged to Customer card
- [ ] Build **Product Performance** with caveat tag for allocated profit
- [ ] Build **Country / Market Performance** with the **Shipping Charged Ratio by Country** chart (revenue-side, not cost)
- [ ] Build **Customer / Repeat Purchase** with guest-checkout disclosure
- [ ] Build **Data Quality** sub-page (include payment fee source split + Woo vs CSV shipping-charged drift)

### Verify
- [ ] Hand-calc 5 orders end-to-end → match cards
- [ ] Save `.pbix`; export DAX to `powerbi/measures/dax_measures.txt`
- [ ] Commit + push

---

## Phase 5 — Fulfillment Enrichment Dashboard

### dbt
- [ ] `marts/operations/dim_supplier.sql` (seed + observed)
- [ ] `marts/operations/fact_fulfillment.sql` joined to `fact_order` by `(site_sk, woo_order_id)`
- [ ] `marts/reconciliation/recon_fulfillment_coverage.sql`
- [ ] Singular: `assert_fulfillment_coverage_at_least_80.sql` (warn)
- [ ] Tests: `not_null(order_sk)`, `relationships(order_sk → fact_order)`

### Power BI
- [ ] Activate **Fulfillment / Operations** page
- [ ] Add fulfillment coverage % to Data Quality page
- [ ] Commit + push

---

## Phase 6 — GA4 BigQuery Modeling

### Access
- [ ] Confirm GA4 BigQuery export per property
- [ ] Create service account (BigQuery Data Viewer + Job User)
- [ ] Save JSON outside repo; set `GOOGLE_APPLICATION_CREDENTIALS`

### Audit deliverable — `docs/GA4_BIGQUERY_AUDIT.md`
- [ ] `notebooks/02_ga4_audit.ipynb` populates the doc with:
  - [ ] available GA4 BigQuery tables (`INFORMATION_SCHEMA.TABLES`)
  - [ ] event name inventory + counts per day (last 7d)
  - [ ] ecommerce event coverage matrix
  - [ ] purchase event inspection (transaction_id, items array)
  - [ ] `transaction_id` coverage % per site
  - [ ] `transaction_id` match rate vs `fact_order.woo_order_id` per site
  - [ ] source/medium/campaign field availability
  - [ ] item array coverage
- [ ] Record activation decision in `docs/GA4_BIGQUERY_AUDIT.md` §10:
  - match rate ≥ 85% → attribution active
  - <85% → GA4 used for funnel + landing pages only
- [ ] Note: GA4 audit lives in **`docs/GA4_BIGQUERY_AUDIT.md`**, not in `WOO_PAYLOAD_AUDIT.md`.

### Pipeline
- [ ] `src/extract/ga4_bigquery.py` (daily reload of D-1)
- [ ] `raw.ga4_events` partitioned by `(event_date, site_code)`

### dbt
- [ ] `dbt/models/staging/ga4/_sources.yml`
- [ ] `stg_ga4_events.sql`
- [ ] `stg_ga4_sessions.sql`
- [ ] `stg_ga4_ecommerce_events.sql`
- [ ] `marts/marketing/dim_channel.sql`, `dim_device.sql`, `dim_page.sql`
- [ ] `marts/marketing/fact_ga4_event.sql`
- [ ] `marts/marketing/fact_ga4_session.sql`
- [ ] `marts/marketing/fact_ga4_pageview.sql`
- [ ] `marts/marketing/fact_ga4_ecommerce_event.sql`
- [ ] `marts/reconciliation/recon_ga4_vs_woo_daily.sql`
- [ ] Tests: `unique(session_sk)`, `accepted_values(event_name)`, soft `relationships(transaction_id → fact_order.woo_order_id)` (warn)

### Power BI
- [ ] Activate **Website Behavior / GA4 Funnel** page
- [ ] Activate **Landing Page Performance** page
- [ ] Add GA4 ↔ Woo metrics to Data Quality page
- [ ] Commit + push

---

## Optional Future Phase — Ads Integration (not part of MVP)

- [ ] (when triggered) Document attribution model in `METRICS_DEFINITION.md` §F
- [ ] (when triggered) Pull spend per platform → `raw.ads_<platform>_daily`
- [ ] (when triggered) `stg_ads_*`, `fact_ad_spend_daily`, `attribution_session_to_order`
- [ ] (when triggered) Activate Marketing Performance page

This phase is **not** required for portfolio completion.

---

## Phase 7 — Synthetic Public Sample + Portfolio Polish

- [ ] Write `scripts/generate_synthetic_woo_sample.py` producing fully synthetic Woo-shaped CSVs (~500 orders, plus synthetic cost enrichment so profit marts work end-to-end)
- [ ] Output to `data/sample_raw/synthetic_*.csv`
- [ ] Confirm Maven sample remains alongside as a second public dataset
- [ ] Add architecture diagram (Mermaid) to README
- [ ] Write 3 "decisions made" mini case studies
- [ ] Capture dashboard screenshots → `powerbi/screenshots/`
- [ ] Add `Makefile` (`make load-raw`, `make dbt-build`, `make all`)
- [ ] Record 3-minute Loom walkthrough
- [ ] Re-scan repo for leakage (no real customer data, keys, tracking IDs)
- [ ] Make repo public
