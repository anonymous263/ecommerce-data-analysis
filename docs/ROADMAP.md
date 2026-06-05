# Roadmap

> Eight phases plus one optional future phase. Cost enrichment is **before** the profit dashboard, because COGS lives in the manual sheet.

---

## Phase 0 — Setup, Privacy, and Source Audit
**Goal:** infrastructure, hard privacy rules, multi-site config.

### Tasks
- Initialize git, create GitHub repo (private at first).
- Strict `.gitignore`: `.env`, `data/raw/`, `Order Management.csv`, `dbt/target/`, `dbt/dbt_packages/`, `__pycache__/`, `.venv/`, `*.pbix.backup`.
- Add `.env.example`.
- Python venv + base deps.
- Postgres 16 in Docker (`docker-compose.yml`).
- Create Postgres schemas: `raw`, `staging`, `marts_core`, `marts_marketing`, `marts_operations`, `marts_recon`.
- `dbt init`; configure `profiles.yml`.
- Generate `PII_SALT` once; store in `.env`; back it up offline.
- Fill `config/sites.yaml` and `dbt/seeds/dim_site_seed.csv`.
- Translate the Vietnamese Maven dictionary docx into `docs/MAVEN_DATA_DICTIONARY.md`.

### Privacy
- `raw.csv_order_management` is **private-only, local-only, gitignored, never exported, never used in the public sample**.
- PII never crosses the `raw → staging` boundary unhashed.
- Public portfolio dataset is fully synthetic.

### Output
- `.gitignore`, `.env.example`, `docker-compose.yml`, `dbt/`, `config/sites.yaml`, `dbt/seeds/dim_site_seed.csv`.

### Acceptance
- `docker compose up -d postgres` brings up DB.
- `dbt debug` connects.
- `git status` confirms no real CSV staged.

---

## Phase 1 — WooCommerce API Raw Ingestion + Payload Audit
**Goal:** every Woo entity in `raw.woo_*` per site, plus a written audit of the actual payload shape.

### Tasks
- Generate read-only WooCommerce REST API keys per site.
- Test API connectivity with `curl`.
- Write `src/extract/woo_api.py` (paginate /orders, /orders/<id>/refunds, /products, /customers, /coupons; per-site loop; high-watermark; idempotent upsert; `_payload JSONB` resilience).
- Land raw tables + `raw.pipeline_state` + `raw.pipeline_runs`.
- **Execute [`docs/WOO_PAYLOAD_AUDIT.md`](WOO_PAYLOAD_AUDIT.md):**
  - 20 recent orders per site
  - order-level + line_items fields
  - **Acowebs `meta_data` keys** for size/type/color/addons
  - custom statuses
  - **payment fee field location** and mapping to `payment_fee_source` enum
  - refund fields and grain (order-level confirmed?)
  - **Woo `shipping_charged` field** (which top-level Woo field carries customer shipping charge?)
  - currency fields per site
- Unit tests on extractor idempotency.

### Output
- `src/extract/woo_api.py`, `src/load/db.py`, `src/load/upsert.py`
- `config/sites.yaml` populated
- `docs/WOO_PAYLOAD_AUDIT.md` filled with real findings

### Acceptance
- Re-running extractor produces zero duplicates.
- `raw.woo_orders` per site matches WP admin within ±0.1%.
- Audit doc has concrete examples (no "TBD") for: Acowebs metadata, payment fee field, shipping_charged field, refund grain.

---

## Phase 2 — dbt Staging + Core Marts (Woo only)
**Goal:** clean, tested marts from WooCommerce raw — **before any cost-related logic**.

### Tasks
- Configure `dbt_project.yml`, `profiles.yml`, `packages.yml` (`dbt_utils`, `dbt_expectations`).
- Define dbt sources for `raw.woo_*`.
- Staging models:
  - `stg_woo_orders` — parse status, currency, per-order FX→USD via `seeds/fx_rates.csv`, **map Woo shipping field → `shipping_charged_src/usd`**, set `payment_fee_usd` + `payment_fee_source`.
  - `stg_woo_order_items` — wire Acowebs variant parsing per audit.
  - `stg_woo_products`
  - `stg_woo_customers` — hash email, drop names/phones/addresses.
  - `stg_woo_refunds` — order-level grain by default; `order_item_sk` nullable.
  - `stg_woo_coupons`
- Core marts (`marts_core`):
  - `dim_date`, `dim_site`, `dim_country`, `dim_product`, `dim_customer_anonymized` (no aggregate fields), `dim_payment_method`
  - `fact_order` — header amounts only (no `revenue_usd`); includes `shipping_charged_*`.
  - `fact_order_item` — official revenue.
  - `fact_refund` — order-level grain.
  - `mart_customer_summary` — repeat behavior aggregates.
- Tests (`schema.yml`): unique, not_null, accepted_values, relationships, `expression_is_true` (revenue ≥ 0, qty > 0).
- `dbt build` passes.

### Output
- `dbt/models/staging/woocommerce/*.sql`
- `dbt/models/marts/core/*.sql` (excluding profit marts)
- `dbt/seeds/dim_site_seed.csv`, `country_iso_map.csv`, `fx_rates.csv`
- `dbt/macros/hash_pii.sql`

### Acceptance
- All dbt tests green.
- `fact_order_item.line_revenue_usd` sums match WooCommerce admin within ±0.5%.
- `fact_order.shipping_charged_usd` populated for orders that have shipping.
- No PII downstream of `stg_woo_customers`.

---

## Phase 3 — Manual Cost Enrichment from the Order Management Sheet
**Goal:** load COGS, design fee, optional payment-fee fallback, and customer-shipping-charge reconciliation from the CSV. **No `actual_shipping_cost_usd` — supplier shipping is already inside COGS.**

### Tasks
- Define `raw.csv_order_management` columns.
- `src/extract/csv_order_management.py`:
  - `pd.read_csv(skiprows=[1,2])`
  - drop PII at load
  - derive `(site_code, woo_order_id)` from `Project` + `Order Code`
  - upsert to `raw.csv_order_management` with `extracted_at`
- Staging:
  - `stg_manual_order_cost_enrichment` — outputs `cogs_usd` (includes supplier shipping), `design_fee_usd`, `payment_fee_fallback_usd`, `csv_revenue_observed_usd`, `csv_profit_observed_usd`, **`csv_shipping_charged_usd`** (recon only), `cost_source`, `cost_allocation_method`, `cost_confidence`. Drops CSV Revenue/Profit/ROI/Profit Margin as official.
  - `stg_manual_fulfillment_enrichment` — supplier, tracking hashes, etc. (Phase 5 uses these.)
- `marts_operations.fact_order_cost`:
  - Order-level grain.
  - Columns: `cogs_usd`, `design_fee_usd`, `payment_fee_fallback_usd`, `cost_source`, `cost_allocation_method`, `cost_confidence`, plus the `csv_*_observed_*` and `csv_shipping_charged_usd` recon columns.
- Profit marts (`marts_core`):
  - `mart_order_profit` with locked formula `revenue_usd − cogs_usd − design_fee_usd − payment_fee_usd`.
  - `mart_product_profit` with allocation (`line_exact` / `allocated_by_revenue_share` / `allocated_by_quantity_share`).
  - `mart_country_profit`.
- Reconciliation views in `marts_recon`:
  - `recon_csv_vs_dbt_revenue`
  - `recon_csv_vs_dbt_profit`
  - **`recon_woo_vs_csv_shipping_charged`** — daily delta of Woo `shipping_charged_usd` vs CSV `csv_shipping_charged_usd`
  - `recon_cost_coverage`
  - `recon_payment_fee_coverage`
- dbt tests:
  - `not_null(order_sk)` on `fact_order_cost`
  - `relationships(order_sk → fact_order)`
  - `accepted_values(cost_allocation_method)` + `accepted_values(cost_source)`
  - `accepted_values(payment_fee_source: api_exact/plugin_parser/seed_estimate/missing)` on `fact_order`
  - `expression_is_true: cost_confidence BETWEEN 0 AND 1`
  - Singular `assert_cost_coverage_tiers.sql` — warns at <80% (red) and <95% (info) per the dashboard gates.
  - Singular `assert_payment_fee_coverage_at_least_80.sql`

### Output
- `src/extract/csv_order_management.py`
- `dbt/models/staging/manual/stg_manual_order_cost_enrichment.sql`
- `dbt/models/staging/manual/stg_manual_fulfillment_enrichment.sql`
- `dbt/models/marts/operations/fact_order_cost.sql`
- `dbt/models/marts/core/mart_order_profit.sql`, `mart_product_profit.sql`, `mart_country_profit.sql`
- `dbt/models/marts/reconciliation/recon_csv_vs_dbt_revenue.sql`, `recon_csv_vs_dbt_profit.sql`, `recon_woo_vs_csv_shipping_charged.sql`, `recon_cost_coverage.sql`, `recon_payment_fee_coverage.sql`

### Acceptance
- Cost coverage ≥ 80% (else profit hidden in Phase 4 dashboard).
- CSV-vs-Woo revenue daily delta per site ≤ 5%.
- Woo vs CSV shipping-charged daily delta per site ≤ 5%.
- `mart_product_profit` carries `cost_allocation_method` + `cost_confidence`.
- No `actual_shipping_cost_usd` exists anywhere in the model.

---

## Phase 4 — Power BI MVP
**Goal:** dashboard pages 1–4 + Data Quality sub-page.

### Tasks
- Connect Power BI Desktop to Postgres marts.
- Author DAX measures from `METRICS_DEFINITION.md` §A, §B, §C, §G (incl. **A7 Shipping Charged to Customer**, **A8 Shipping Charged/Revenue**, **G4 Shipping Charged Ratio by Country**), §I, §H.
- **Implement tier-gated profit visibility per [DASHBOARD_SPEC.md §K](DASHBOARD_SPEC.md):**
  - <80% Cost Coverage → hide profit visuals + banner.
  - 80–95% → show with yellow chip.
  - ≥95% → fully trusted.
- Build Pages 1–4 + Data Quality.
- Add the profit caveat banner (COGS includes supplier shipping).
- Hand-calc 5 orders end-to-end.

### Acceptance
- 4 pages render with real Woo + cost data.
- Reconciliation within ±0.5%.
- Tier gating verified by toggling cost coverage on a sample.

---

## Phase 5 — Fulfillment Enrichment Dashboard
**Goal:** add operational visibility from `stg_manual_fulfillment_enrichment`.

### Tasks
- `marts_operations.dim_supplier` (seed + observed).
- `marts_operations.fact_fulfillment` joined to `fact_order` by `(site_sk, woo_order_id)`.
- `marts_recon.recon_fulfillment_coverage`.
- Activate **Fulfillment / Operations** page.

### Acceptance
- Fulfillment page shows avg fulfillment days, on-time %, supplier scorecard.
- Coverage panel shows `% orders with fulfillment enrichment`.

---

## Phase 6 — GA4 BigQuery Modeling
**Goal:** website behavior, gated by [GA4_BIGQUERY_AUDIT.md](GA4_BIGQUERY_AUDIT.md).

### Tasks
- Confirm GA4 BigQuery export.
- Service account, JSON key, outside repo.
- **Fill `docs/GA4_BIGQUERY_AUDIT.md`** — tables available, event names, ecommerce coverage, purchase events, `transaction_id` coverage, `transaction_id` match rate to Woo, traffic source fields, item array coverage. **Record activation decision (attribution active vs disabled).**
- Write `src/extract/ga4_bigquery.py` (daily reload of `events_YYYYMMDD` for D-1).
- dbt models: `stg_ga4_events`, `stg_ga4_sessions`, `stg_ga4_ecommerce_events`, `fact_ga4_*`.
- `marts_recon.recon_ga4_vs_woo_daily`.
- Activate Website Behavior + Landing Page pages.

### Acceptance
- ≥7 days GA4 loaded.
- Funnel page renders with non-zero counts.
- Audit decision recorded in `docs/GA4_BIGQUERY_AUDIT.md`.

---

## Optional Future Phase — Ads Integration & Attribution
**Not part of MVP.** Activated only if ads run.

---

## Phase 7 — Synthetic Public Sample + Portfolio Polish
**Goal:** publish safely with fully synthetic data.

### Tasks
- Write `scripts/generate_synthetic_woo_sample.py` (~500 fully synthetic orders + matching synthetic cost enrichment so profit marts compute end-to-end).
- Confirm no real customer data, keys, tracking IDs, or PII anywhere in the public repo.
- Architecture diagram (Mermaid).
- 3 "decisions made" case studies.
- Dashboard screenshots.
- `Makefile`.
- Loom walkthrough.
- Make repo public.

### Acceptance
- `make all` from a clean clone with only synthetic data populates a working dashboard.
- Repo scan: no PII, no real keys, no real tracking IDs.
- README explicitly states the public data is synthetic.
