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
- [x] `docker compose up -d postgres` (container `ecommerce_postgres`, healthy)
- [x] Create schemas `raw`, `staging`, `marts_core`, `marts_marketing`, `marts_operations`, `marts_recon` (via `sql/init/01_create_schemas.sql`; all 6 confirmed present)
- [x] `dbt init` in `dbt/` (project `ecommerce_analytics` scaffolded)
- [x] Configure `~/.dbt/profiles.yml` (env-var driven; `dbt debug` → **all checks passed**)
- [x] Configure `dbt/dbt_project.yml` (per-folder materializations)
- [x] `dbt/packages.yml` with `dbt-labs/dbt_utils` + `calogica/dbt_expectations`
- [x] `dbt deps && dbt debug` (both pass; dbt-core 1.10.21, adapter postgres 1.10.0)

### Multi-site config
- [x] Create `config/sites.yaml` listing site `FOS` (multi-currency: USD/GBP/CAD/EUR), plus any others
- [x] Create `dbt/seeds/dim_site_seed.csv` mirroring the same site list
- [x] Add a singular dbt test asserting site list matches between yaml and seed — `dbt/tests/singular/assert_site_seed_matches_config.sql` (in-warehouse guard); yaml↔seed field parity enforced by `tests/test_site_config_matches_seed.py` (pytest), since dbt/SQL cannot read the yaml

### Source audit
- [x] Open `[Đọc cái này trước] Tài liệu Data Dictionary.docx` → save translated summary to `docs/MAVEN_DATA_DICTIONARY.md`
- [ ] Fill `dbt/seeds/dim_supplier_seed.csv` with Printify SLA where known — _deferred (not a Phase 0 blocker): Printify has no fixed contractual SLA, so `sla_days` is left null until an authoritative value is known_
- [x] Fill `dbt/seeds/country_iso_map.csv` (`UK → GB`, etc.)
- [x] Fill `dbt/seeds/fx_rates.csv` (`date, currency, usd_rate`) — static seed initially (replaceable by FX API later)
- [x] Add `dbt/seeds/payment_fees.csv` placeholder (fallback only)
- [x] `dbt seed` (all 7 seeds load via `--full-refresh`; `dbt build` green → PASS=8, 0 errors)

### WooCommerce credentials
> ⚠️ **Security (2026-07-14):** the FOS key/secret had been hardcoded in `config/sites.yaml` and pushed to GitHub. Fixed in-repo (sanitized to env-var references, single root commit history-scrubbed, force-pushed), but the exposed pair must be treated as **compromised**. `sites.yaml` now references env-var *names* only; real values live in `.env`.
- [x] Generate read-only consumer key/secret per site — **rotate FOS: the leaked key `ck_7d89f0…` must be revoked, not reused** _(owner action — needs WooCommerce login)_
- [x] Store new `WOO_<SITECODE>_KEY` / `WOO_<SITECODE>_SECRET` in `.env` (currently placeholders)
- [x] Verify with `curl 'https://<domain>/wp-json/wc/v3/orders?per_page=1' -u <key>:<secret>`

---

## Phase 1 — WooCommerce API Raw Ingestion + Payload Audit

### Helpers
- [x] `src/utils/http.py` (httpx + exponential backoff on 429/5xx, page-based `paginate` generator)
- [x] `src/utils/logging.py`
- [x] `src/load/db.py` (SQLAlchemy engine factory + `apply_sql_file` DDL runner)
- [x] `src/load/upsert.py` (idempotent UPSERT on `(site_code, woo_<entity>_id)`; PK excluded from SET; JSONB cast)
- [x] `src/utils/config.py` (loads `config/sites.yaml` → `Site`; resolves creds via `key_env`/`secret_env` indirection) — supporting helper
- [x] `conftest.py` (puts project root on `sys.path` so tests can `import src`) — supporting

### Raw DDL
- [x] `sql/ddl/01_raw_woo.sql`: `raw.woo_orders`, `raw.woo_order_items`, `raw.woo_products`, `raw.woo_customers`, `raw.woo_refunds`, `raw.woo_coupons`, `raw.pipeline_state`, `raw.pipeline_runs`
- [x] Each carries `site_code`, `extracted_at`, `_payload JSONB`, PK on `(site_code, woo_<entity>_id)`
- [x] Apply to Postgres — all 8 raw tables created in `ecommerce_postgres` (2026-07-15): `woo_orders`, `woo_order_items`, `woo_products`, `woo_customers`, `woo_refunds`, `woo_coupons`, `pipeline_state`, `pipeline_runs`

### Extractor
- [x] `src/extract/woo_api.py`:
  - [x] paginate orders with `modified_after=<watermark>`
  - [x] for each order fetch `/refunds`
  - [x] paginate products, customers, coupons
  - [x] upsert idempotently
  - [x] update watermark only on success
  - [x] log to `raw.pipeline_runs`
- [x] `tests/test_woo_api.py` with mocked payloads (idempotency) — httpx `MockTransport` + fake engine, no DB/network
- [x] `pytest -q` passes — **56 passed** (12 existing + 44 Phase 1); implementation independently Opus-reviewed and hardened (watermark same-second overlap, orphan-free order-item replace, Retry-After cap)
- [x] Backfill site `FOS` (2026-07-15) — 4757 orders, 5190 items, 34 refunds, 58168 products, 79 coupons, 0 customers (guest checkout); run logged `success` in `raw.pipeline_runs` (~30 min), watermark `FOS/orders → 2026-07-15T00:00:39Z`
- [x] Re-run extractor → no duplicates, row count unchanged — orders loaded in the first (killed) run **and** re-loaded on backfill, yet `raw.woo_orders` = 4757 with **0 duplicate keys** (idempotent upsert proven)
- [x] Reconcile `raw.woo_orders` row count vs WP admin (≤0.1%) — 4757 landed = 4757 `X-WP-Total` (exact, 0% delta)

### Payload Audit — `docs/WOO_PAYLOAD_AUDIT.md` ✅ COMPLETE (2026-07-15)
- [x] ~~Pull 20 recent orders~~ → audited over the **full backfill** in `raw.woo_*` (4757 orders etc.) — stronger basis than a 20-order sample; introspected `_payload` structurally (keys/meta-keys/enums only, no PII)
- [x] Fill order-level fields table (§2)
- [x] Fill `line_items[]` fields table (§3)
- [x] Document Acowebs/WCPA `meta_data` keys (§4) — `Size`/`Color`/`Style`/`Fit Type`/`Print on the` + `_WCPA_order_meta_data`; all products `simple` (variants via addons, not Woo variations)
- [x] Document product_type / gender / size parseability (§4) — size/color/style parseable from item meta; gender only a `Fit Type` proxy
- [x] Document custom order statuses (§5) — **none**; all 6 are standard Woo statuses
- [x] Document payment fee field location (§6) — order `meta_data` `_cs_stripe_fee`/`_cs_paypal_fee` (79.5% coverage → `plugin_parser`); `fee_lines` = tips, not fees
- [x] Document refund fields + grain (§7) — **order-level confirmed** (0/34 refunds have `line_items`)
- [x] Write summary + dbt staging implications (§11)
- [ ] Push (commits `f1e392e`, `5c789b6`, `7797964`, `473f2fc` + audit not yet pushed to GitHub)

---

## Phase 2 — dbt Staging + Core Marts

### Sources
- [x] `dbt/models/staging/woocommerce/_sources.yml` for all `raw.woo_*`
- [x] Source `not_null`/`unique` tests

### Macros
- [x] `dbt/macros/hash_pii.sql` — SHA-256 + `env_var('PII_SALT')` (Postgres built-in `sha256(bytea)`, NULL on blank)

### Staging models
- [x] `stg_woo_orders.sql` — status, currency, FX→USD via seed, PII hashed/dropped, `shipping_total → shipping_charged_src/usd`, `payment_fee_usd`+`payment_fee_source` from `_cs_*_fee` meta (`plugin_parser`/`missing`; `seed_estimate` deferred — seed placeholder)
- [x] `stg_woo_order_items.sql` — exploded, `site_sk`, WCPA variant parsing (Size/Color/Style/Fit Type/Print location, price-suffix stripped)
- [x] `stg_woo_products.sql`
- [x] `stg_woo_customers.sql` — hash email; drop names/phones/addresses (source empty — guest checkout)
- [x] `stg_woo_refunds.sql` — order-level grain; `order_item_sk` NULL
- [x] `stg_woo_coupons.sql`

### Mart models (core)
- [x] `marts/core/dim_date.sql`
- [x] `marts/core/dim_site.sql` (from seed)
- [x] `marts/core/dim_country.sql` (from order data + `XX` unknown; seed enriches)
- [x] `marts/core/dim_product.sql` — catalog grain `(site, woo_product_id)`; variant attrs live on `fact_order_item` (documented deviation from DATA_MODEL §5.3)
- [x] `marts/core/dim_customer_anonymized.sql` (hash only, no aggregates)
- [x] `marts/core/dim_payment_method.sql`
- [x] `marts/core/fact_order.sql` — header amounts only (**no `revenue_usd`**); `shipping_charged_src/usd`, `payment_fee_usd`, `payment_fee_source`
- [x] `marts/core/fact_order_item.sql` — official revenue; `order_status` + `is_revenue_status` flag
- [x] `marts/core/fact_refund.sql` — order-level grain
- [x] `marts/core/mart_customer_summary.sql` — `total_profit_usd` NULL until Phase 3

### Tests
- [x] Author `dbt/models/schema.yml`:
  - [x] `unique` + `not_null` on PKs
  - [x] `relationships` FK → dim
  - [x] `accepted_values` on status, currency, `payment_fee_source`, `event_type`, `order_status`
  - [x] `expression_is_true: line_revenue_usd >= 0` (+ `refund_amount_usd >= 0`, `fx_rate_to_usd not_null`)
  - [x] `expression_is_true: quantity > 0`
- [x] `dbt build` green — **PASS=141, WARN=0, ERROR=0**

### Verify & commit
- [x] Hand-calc 5 orders' Woo revenue → match `fact_order_item` (5/5 match; incl. EUR order)
- [ ] `dbt docs generate && dbt docs serve` — verify lineage _(optional; deferred)_
- [x] Commit (`<phase2>`); [ ] push _(pending)_

---

## Phase 3 — Manual Cost Enrichment

### Extract

> **Manual CSV PII rule:** for the manual Order Management CSV, unnecessary PII columns such as `Name`, `Email`, `Phone`, and `Ship to` are dropped **before** loading into `raw.csv_order_management`. Therefore `raw.csv_order_management` is **not** a byte-for-byte copy of the full sheet; it is a private raw operational extract with PII removed at ingestion. Tracking IDs and fulfillment URLs may be loaded to raw but **must** be hashed before staging/marts.

- [x] `src/extract/csv_order_management.py`:
  - [x] `pd.read_csv(skiprows=[1,2])`
  - [x] **drop PII (`Name`, `Email`, `Phone`, `Ship to`) BEFORE writing to `raw.csv_order_management`** — raw is not a full copy of the sheet
  - [x] normalize column names (whitespace, ASCII-fold diacritics)
  - [x] derive `(site_code, woo_order_id)` from `Project` + `Order Code`
  - [x] forward-fill order-level fields (by `Order Code`), then dedupe to order grain
  - [x] TRUNCATE-and-reload `raw.csv_order_management` with `extracted_at` (snapshot semantics, per locked CSV rules)
  - [x] keep `Tracking ID`, `Tracking Deliver URL`, `Fulfill URL` in `_payload` at this stage (hashed in Phase 5 staging, not at load)
- [x] `tests/test_csv_order_management.py` — header skip + PII drop + forward-fill + dedupe + symbol strip + currency classification (20 tests, DB-free)

### dbt staging
- [x] `dbt/models/staging/manual/_sources.yml`
- [x] `stg_manual_order_cost_enrichment.sql` — outputs (order-currency money kept as `*_src`, FX applied in `fact_order_cost`, matching the Woo staging→fact pattern):
  - `cogs_usd` (includes supplier fulfillment/shipping fee)
  - `design_fee_usd`
  - `payment_fee_fallback_usd` (only used when Woo cannot provide exact value)
  - `csv_revenue_observed_usd` (recon only)
  - `csv_profit_observed_usd` (recon only)
  - **`csv_shipping_charged_usd`** (recon only — the CSV `Shipping` column is the *customer shipping charge*, NOT supplier cost)
  - `cost_source`, `cost_allocation_method`, `cost_confidence`
  - **Drops** CSV Revenue/Profit/ROI/Profit Margin as official metrics
  - **Does NOT produce** an `actual_shipping_cost_usd` field
- [ ] `stg_manual_fulfillment_enrichment.sql` — parse supplier `#<store>.<order>`; hash tracking ID + URL — _deferred to **Phase 5** (fulfillment enrichment): tracking IDs are hashed in Phase 5 staging per the Extract note above (L151), not a Phase 3 gate_

### dbt marts
- [x] `marts/operations/fact_order_cost.sql` — order-level cost with `cost_source`, `cost_allocation_method`, `cost_confidence` (no separate supplier-shipping cost field)
- [x] `marts/core/mart_order_profit.sql` — contribution profit = `revenue_usd − cogs_usd − design_fee_usd − payment_fee_usd` (no shipping subtraction)
- [x] `marts/core/mart_product_profit.sql` — revenue-share allocation default
- [x] `marts/core/mart_country_profit.sql`
- [x] `marts/core/mart_customer_summary.sql` — `total_profit_usd` wired from `mart_order_profit` (was NULL pending Phase 3)

### Reconciliation
- [x] `marts/reconciliation/recon_csv_vs_dbt_revenue.sql`
- [x] `marts/reconciliation/recon_csv_vs_dbt_profit.sql`
- [x] **`marts/reconciliation/recon_woo_vs_csv_shipping_charged.sql`** — daily delta of Woo `shipping_charged_usd` vs CSV `csv_shipping_charged_usd` per site
- [x] `marts/reconciliation/recon_cost_coverage.sql`
- [x] `marts/reconciliation/recon_payment_fee_coverage.sql` — overall % + breakdown by `payment_fee_source`

### Tests
- [x] `not_null(order_sk)` on `fact_order_cost`
- [x] `relationships(order_sk → fact_order)` on `fact_order_cost`
- [x] `accepted_values(cost_allocation_method)` on `fact_order_cost`
- [x] `accepted_values(cost_source: manual_csv, supplier_api)` on `fact_order_cost`
- [x] `accepted_values(payment_fee_source: api_exact, plugin_parser, seed_estimate, missing)` on `fact_order`
- [x] `expression_is_true: cost_confidence BETWEEN 0 AND 1`
- [x] Singular: `assert_cost_coverage_tiers.sql` — warns while below the green (<95%) tier per [METRICS_DEFINITION.md §J](docs/METRICS_DEFINITION.md)
- [x] Singular: `assert_payment_fee_coverage_at_least_80.sql` (warn)
- [x] `dbt build` green — **PASS=190, WARN=2 (both intended coverage warnings), ERROR=0**

### Verify
- [x] Verify whether WooCommerce shipping total matches CSV `Shipping` per order using `recon_woo_vs_csv_shipping_charged` (target daily delta ≤ 5%) — **overall delta 2.24% ✅** (like-for-like covered set; 958/1047 days = 91.5% within ≤5%)
- [x] Cost coverage tier confirmed — **98.79% (3769/3815 revenue orders with real COGS) → green (≥95%)** (post-`727055c`: coverage requires `cogs_usd > 0` over revenue orders); payment-fee coverage 79.50% (plugin_parser), below the 80% chip threshold
- [x] CSV revenue vs Woo daily delta ≤ 5% — **overall delta 3.80% ✅** (CSV Revenue is gross ≈ line + shipping; compared vs dbt gross = line revenue + `shipping_charged_usd`)
- [x] Hand-reconcile 5 sample orders end-to-end (revenue from Woo, cost from CSV, profit from mart, customer shipping charge from Woo) — **all 5 reconcile exactly: `contribution_profit_usd == net_rev − cogs − design_fee − payment_fee`**
- [x] Confirm no `actual_shipping_cost_usd` references remain anywhere in dbt models (guarded by `tests/test_repo_scaffold.py::test_no_forbidden_shipping_cost_field_in_implementation_scaffold`)
- [x] Commit + push — **pushed; `origin/main` @ `727055c` (631c8c1 feat + 9914ca6 + 727055c), zero unpushed commits**

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
