# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A private analytics warehouse (portfolio second) for several **WooCommerce POD stores** (print-on-demand apparel fulfilled by external suppliers). It turns orders, costs, and web behavior into a Kimball star schema and Power BI dashboards.

**Current state: Phases 0–3 complete, Phase 4 (Power BI) in progress.** Live and working:

- **Infra** — Postgres 16 in Docker (`ecommerce_postgres`, all six schemas), dbt-core 1.10.21 / dbt-postgres 1.10.0, 7 seeds.
- **Phase 1** — WooCommerce ingestion: `src/extract/woo_api.py` (incremental watermark, idempotent upsert, run logging) landing `raw.woo_*` via `sql/ddl/01_raw_woo.sql`; audit locked in `docs/WOO_PAYLOAD_AUDIT.md`.
- **Phase 2–3** — 26 dbt models: 7 staging, 12 core marts (facts/dims + `mart_order_profit`, `mart_product_profit`, `mart_customer_summary`), `fact_order_cost`, and 6 reconciliation models. 3 singular tests, 2 macros.
- **Phase 3 cost load** — `src/extract/csv_order_management.py` (PII columns dropped at ingestion).
- **Phase 4** — Power BI `.pbip` project tracked as TMDL text: 12-table semantic model, relationships, DAX measures, 6 report pages. **This is the active work** — see `powerbi/CAPSTONE_BUILD_GUIDE.md`.
- **Tests** — 90 pytest tests passing.

**Not started:** Phase 5 (`fact_fulfillment`), Phase 6 (GA4 — `sql/ga4/` and GA4 staging are still empty), Phase 7 (synthetic public sample — `data/sample_raw/` is `.gitkeep` only). Optional deferred: Printify SLA fill in `dim_supplier_seed.csv`. When implementing a new phase, read the relevant doc first, then create the files it describes.

## Architecture (the big picture)

Four extract/load pipelines feed one dbt transformation graph feeding Power BI:

```
Sources → Python EL (extract/load only) → Postgres raw → dbt (raw→staging→marts) → Power BI
```

- **Python does EL only** — pull, land, log. It never applies business logic. Lands raw API/CSV responses into the `raw` schema (append-only, every row carries `site_code`, `extracted_at`, `_payload` JSONB).
- **dbt owns every transform** — typing, FX conversion, PII hashing, joins, cost allocation, profit, tests, docs. Schemas: `raw` (Python) → `staging` → `marts_core` / `marts_marketing` / `marts_operations` / `marts_recon` (all dbt).
- **Multi-site:** every row carries `site_code` / `site_sk`. Order natural key = `site_code + woo_order_id`. Sites are configured in `config/sites.yaml` and mirrored in `dbt/seeds/dim_site_seed.csv` (a test asserts they match).

### Source-of-truth mapping (do not violate)

| Domain | System of record |
|---|---|
| Orders, items, products, customers, refunds, status, **customer shipping charge** | **WooCommerce REST API** |
| **COGS** (incl. supplier fulfillment/shipping fee), design fee, supplier, tracking, fulfillment | **Manual `Order Management.csv`** (Google Sheet export) |
| Sessions, events, funnel, landing pages | **GA4 BigQuery export** |
| Ad spend / ROAS / CAC | **Optional Future** — no ads running; not part of MVP |
| `E-commerce data sample/` (Maven Fuzzy Factory) | Practice/demo only — isolated namespace, never mixed with real marts |

## Non-negotiable domain rules

These are the project's load-bearing invariants. Violating them silently corrupts every metric — preserve them in code, DAX, and review.

1. **Revenue has two components, each living once.** **Product revenue** lives at `fact_order_item.line_revenue_usd` (item grain; `fact_order` has **no product-revenue column** — prevents order×item double-count). **Customer shipping charge** lives at `fact_order.shipping_charged_usd` (order grain). The profit revenue base combines them in `mart_order_profit`: `gross_revenue_usd = gross_product_revenue_usd + shipping_charged_usd`. Product-only rollups still sum items; the order-total revenue basis adds shipping.
2. **Contribution profit = `net_revenue_usd − cogs_usd − design_fee_usd − payment_fee_usd`**, where `net_revenue_usd = (product revenue + customer shipping) − effective_refund`. **Customer shipping IS revenue** — the store received that money. `cogs_usd` is the all-in per-order fulfilment cost (it already contains whatever the supplier charged for shipping), so the shipping the customer paid AND the fulfilment cost both appear — never one without the other. (Approach A, adopted 2026-07-21; the earlier "no shipping in the revenue base" rule understated FOS profit by ~$40k — see `docs/METRIC_CHANGES.md`.)
3. **There is no `actual_shipping_cost_usd` field anywhere** — not in models, not in DAX. The concept does not exist in the data. If you see a reference to it, it's a bug.
4. **The CSV `Shipping` column = shipping charged to the *customer*** (revenue-side), NOT supplier cost. The official customer shipping charge is Woo's `fact_order.shipping_charged_usd`, which **is counted as revenue** (rule #2). The CSV column is used only for the like-for-like shipping recon (`recon_woo_vs_csv_shipping_charged`).
5. **CSV `Revenue` / `Profit` / `ROI` / `Profit Margin` are never copied as official metrics** — they appear only in `marts_recon.recon_csv_vs_dbt_*` for drift monitoring.
6. **`cogs_usd` (CSV column U) is the ALL-IN per-order fulfilment cost** — it already includes the supplier fulfilment/shipping fee. Do not decompose or model supplier shipping separately (that concept does not exist in the data). This is exactly why customer shipping must be counted as revenue (rule #2): the store pays the all-in COGS to fulfil the order AND collects shipping from the customer, so both belong in the P&L.

## Privacy (hard rules)

- **`Order Management.csv` and all real Woo extracts are gitignored** — local-only, never committed, never exported, never in the public sample.
- **Manual CSV PII rule:** drop `Name`, `Email`, `Phone`, `Ship to` *before* writing to `raw.csv_order_management`. So `raw.csv_order_management` is **not** a byte-for-byte copy of the sheet. Tracking IDs / fulfillment URLs may land in raw but **must be hashed before staging/marts**.
- **PII never crosses `raw → staging` unhashed.** dbt staging hashes emails via `SHA-256(lower(trim(email)) || PII_SALT)` (macro `hash_pii.sql`) and drops names/phones/addresses.
- Guest checkout means customer linkage is by hashed email only — `PII_SALT` must be backed up offline; losing it breaks all customer linkage.
- The **public repo ships only a fully synthetic dataset** (plus the Maven sample). No sanitized real-customer data, ever.
- Secrets live in `.env` (gitignored): `POSTGRES_*`, `WOO_<SITECODE>_KEY`/`_SECRET`, `PII_SALT`, `GOOGLE_APPLICATION_CREDENTIALS`. `.env.example` is committed.

## Data-quality gating (drives dashboards)

Coverage thresholds aren't just tests — they gate what the dashboard shows. Cost coverage is tiered: **<80% → hide profit visuals + "Profit unavailable" banner; 80–95% → show with yellow "partial coverage" chip; ≥95% → fully trusted.** Payment-fee coverage <80% (measured over **revenue orders**, same basis as cost coverage) adds an "estimated payment fee" chip. `payment_fee_source` is always one of `'api_exact' | 'plugin_parser' | 'seed_estimate' | 'missing'`. See `docs/METRICS_DEFINITION.md §J` and `docs/DASHBOARD_SPEC.md §K`.

## Phased build order

Cost enrichment (Phase 3) comes **before** the Power BI MVP (Phase 4) because COGS only exists in the manual sheet. Two audit docs are gates: `docs/WOO_PAYLOAD_AUDIT.md` (Phase 1) locks the variant parser, payment-fee parser, and refund grain; `docs/GA4_BIGQUERY_AUDIT.md` (Phase 6) gates GA4↔Woo attribution (≥85% `transaction_id` match → attribution active, else funnel/landing only).

| Phase | Outcome |
|---|---|
| 0 | Postgres + dbt up, privacy guards, site config, source audit |
| 1 | `raw.woo_*` ingestion + payload audit |
| 2 | dbt staging + core marts (sales/orders/products/customers/refunds) |
| 3 | Manual cost enrichment → `fact_order_cost`, profit marts |
| 4 | Power BI MVP |
| 5 | Fulfillment enrichment → `fact_fulfillment` |
| 6 | GA4 BigQuery modeling (audit-gated) |
| 7 | Synthetic public sample + portfolio polish |

`TASKS.md` is the authoritative, checkbox-level task list — keep it in sync when completing work.

## Commands

> None are wired up yet — these are the planned/intended commands from `TASKS.md` and `docs/PIPELINE_DESIGN.md`. The eventual `Makefile` (Phase 7) will expose `make load-raw`, `make dbt-build`, `make all`.

```powershell
# Environment (Phase 0)
docker compose up -d postgres            # Postgres 16 in Docker
pip freeze > requirements.txt            # base deps incl. dbt-core, dbt-postgres, pandas, httpx, sqlalchemy

# dbt (run from dbt/ once it exists)
dbt deps                                 # install dbt_utils + dbt_expectations
dbt debug                                # verify Postgres connection / profile
dbt seed                                 # load seeds (sites, fx_rates, country map, suppliers)
dbt build                                # run + test all models
dbt build --select stg_woo_orders+       # build one model and everything downstream
dbt test --select fact_order_item        # run tests for a single model
dbt docs generate && dbt docs serve      # lineage graph

# Python ELT + tests
python -m src.extract.woo_api            # Phase 1 extractor (intended entrypoint)
pytest -q                                # full test suite
pytest tests/test_woo_api.py -q          # single test file
```

## Tech stack

Python 3.11 (extract/load) · PostgreSQL 16 in Docker · dbt-core + dbt-postgres · BigQuery (GA4 source) · Power BI Desktop. Git + GitHub (repo not yet initialized).

## Where things will live

- `src/extract/`, `src/load/`, `src/utils/` — Python EL (entrypoints: `woo_api.py`, `csv_order_management.py`, `ga4_bigquery.py`). See `docs/PIPELINE_DESIGN.md §12`.
- `sql/ddl/` — raw-schema DDL (e.g. `01_raw_woo.sql`).
- `dbt/models/staging/{woocommerce,ga4,manual}/`, `dbt/models/marts/{core,marketing,operations,reconciliation}/`, `dbt/seeds/`, `dbt/macros/`, `dbt/tests/singular/` — see full tree in `docs/PIPELINE_DESIGN.md §7`.
- `powerbi/` — `.pbix` files, exported DAX, screenshots.
- `data/raw/` (gitignored, real) · `data/sample_raw/` (synthetic, public) · `data/processed/`.

## Reading order for new work

`README.md` (overview + rules) → `TASKS.md` (what to do next) → the phase's spec doc: `docs/DATA_MODEL.md` (schemas, grains, profit formula), `docs/PIPELINE_DESIGN.md` (EL + dbt layout), `docs/METRICS_DEFINITION.md` (metric/DAX definitions), `docs/DASHBOARD_SPEC.md` (pages + gating), `docs/DATA_AUDIT.md` (PII inventory). `docs/CODEX_REVIEW.md` holds prior review notes.
