# Ecommerce Data Analysis — WooCommerce + POD + GA4

> A private business warehouse first, a portfolio second. **WooCommerce REST API is the source of truth** for revenue, orders, products, customers, refunds, and customer shipping charge. A **manual Order Management sheet** provides initial cost + fulfillment enrichment — COGS (which already includes supplier fulfillment/shipping fee where applicable), design fee, supplier, tracking, and operational flags. **GA4 BigQuery** delivers website behavior. **dbt** owns transforms. **Ads is optional future**, not part of the MVP.

**Status:** Phases 0–3 shipped, Phase 4 (Power BI) in progress. The warehouse runs end to end today — WooCommerce ingestion → 26 dbt models → profit marts → a Power BI semantic model. GA4 (Phase 6) and the synthetic public sample (Phase 7) are not started.

![Executive Overview dashboard — KPI cards, monthly revenue/profit trend, top markets, and a revenue-to-profit waterfall](powerbi/screenshots/overview.png)

<sub><b>Executive Overview</b> — the profit bridge on the lower right decomposes revenue into COGS, design fee, and payment fee to land on contribution profit. Note that <i>Net rev</i> ($72.1K) exceeds <i>Product Revenue</i> ($55.4K): customer shipping is counted as revenue, per the profit rule in §3. Dashboard is still in progress; figures shown are filtered to 2025–2026, not the full history.</sub>

### What's built

| Layer | Shipped |
|---|---|
| **Extract / Load** (Python 3.11) | Incremental WooCommerce pull with high-watermark state, idempotent upserts, and per-run logging (`src/extract/woo_api.py`); manual cost-sheet loader that drops PII at ingestion (`src/extract/csv_order_management.py`) |
| **Warehouse** (Postgres 16) | `raw` → `staging` → `marts_core` / `marts_operations` / `marts_recon`, DDL in `sql/ddl/` |
| **Transforms** (dbt) | **26 models** — 7 staging, 12 core marts (facts + conformed dims + `mart_order_profit`, `mart_product_profit`, `mart_customer_summary`), `fact_order_cost`, and **6 reconciliation models** that diff the warehouse against the operator's spreadsheet |
| **Quality** | 7 seeds, 3 singular tests, schema tests, coverage-tier gates, and **90 passing pytest tests** |
| **BI** | Power BI `.pbip` project committed as **TMDL text** (diffable, reviewable): 12-table semantic model, relationships, DAX measures, 6 report pages |

Two details worth calling out for reviewers:

- **The Power BI model is version-controlled as text, not a binary.** `.pbix` is gitignored precisely because it embeds a full data extract; the `.pbip`/TMDL project is the source of truth. See [`powerbi/`](powerbi/).
- **Reconciliation is a first-class layer.** Six `recon_*` models continuously diff dbt output against the manually maintained sheet, so metric drift is detected rather than assumed away.

---

## 1. Business Context

I operate several **WooCommerce stores selling POD products** (mostly apparel — t-shirts, tank tops, hoodies) fulfilled by multiple external suppliers. Some suppliers have APIs, some do not. Today's operational truth lives in a manually maintained Google Sheet (exported as `Order Management.csv`) — that sheet is the only place where COGS, which already includes supplier fulfillment/shipping fee where applicable, design fees, supplier identifiers, tracking IDs, and customer shipping charge for reconciliation are recorded for every order. The sheet is **operationally valuable but not authoritative** for revenue or profit.

This project replaces ad-hoc reporting with a real warehouse that answers:

- Which products and topics are actually profitable after fees, COGS, and shipping?
- Which countries / markets buy most at the best margin?
- Where do visitors drop off in the funnel: session → view_item → add_to_cart → begin_checkout → purchase?
- Which suppliers fulfill fastest? Which carriers cause delivery exceptions?
- How does each site compare?

## 2. Project Objectives

1. Build a **PostgreSQL warehouse** with a Kimball star schema fed primarily by WooCommerce, enriched by the manual cost/fulfillment sheet, and extended by GA4 BigQuery.
2. Build **Python extract/load** scripts that land raw API responses into the `raw` schema, and **dbt** models that transform `raw → staging → marts`.
3. Build **Power BI dashboards** that drive decisions on product mix, pricing, suppliers, and operations.
4. Ship a **public portfolio** version that uses a **fully synthetic** dataset — no sanitized real data, ever.

## 3. Source-of-Truth Mapping

| Domain | System of record | Mechanism | Phase |
|---|---|---|---|
| Orders, order items, products, customers, coupons, **order status** | **WooCommerce REST API** | Daily incremental pull → `raw.woo_*` | 1 |
| Refunds / cancellations | **WooCommerce** (refunds endpoint or order status) | Same as above | 1–2 |
| **COGS (incl. supplier fulfillment/shipping fee), design fee, supplier, tracking, fulfillment URL, carrier, "Check Sent", delivery notes** | **Manual Order Management sheet / CSV** | Periodic load → `raw.csv_order_management` | 3 (cost) + 5 (fulfillment) |
| Sessions, events, funnel steps, landing pages, traffic source | **GA4 BigQuery export** | Daily extract → `raw.ga4_*` | 6 |
| Ad spend / ROAS / MER / CAC | Ad platforms — **not currently running** | Deferred | **Optional Future** |
| Practice / demo data only | `E-commerce data sample/` (Maven Fuzzy Factory) | Static, isolated namespace | Phase 0 practice / Phase 7 demo |

**Hard rules:**
- The CSV is **not** the source of truth for revenue, orders, refunds, customer shipping charge, or final profit.
- The CSV **is** the source of truth (for now) for **COGS — which already includes the supplier fulfillment/shipping fee** — plus design fee, supplier, tracking, and other operational fields WooCommerce does not store.
- The CSV `Shipping` column is **shipping charged to the customer** (revenue-side), *not* supplier shipping cost. The official customer shipping charge is `fact_order.shipping_charged_usd`, which **is counted as revenue** in the profit base (Approach A); the CSV column is used only for reconciliation in `recon_woo_vs_csv_shipping_charged`.
- The CSV's `Revenue`, `Profit`, `ROI`, `Profit Margin` columns are **never** copied as official metrics — only into `marts_recon.recon_csv_vs_dbt_*` for drift monitoring.
- There is no `actual_shipping_cost_usd` field in the model. **Customer shipping is revenue** (added to the profit base); the *supplier* shipping fee is already inside COGS (the all-in fulfilment cost), so shipping is never subtracted as a cost. See `docs/METRIC_CHANGES.md` (Approach A, 2026-07-21).
- `raw.csv_order_management` is **private-only, local-only, gitignored, never exported, and never used in the public sample**.
- Maven sample lives in its own namespace and never mixes with real Woo marts.

## 4. Proposed Architecture

```
┌────────────────────────┐
│  Sources               │
│  - WooCommerce REST API│ (source of truth: revenue, orders, refunds)
│  - GA4 BigQuery export │ (source of truth: behavior)
│  - Order Management    │ (source of truth: COGS + fulfillment enrichment)
│    sheet / CSV         │
│  - Ads platforms       │ (optional future — none running)
│  - Maven sample        │ (practice/demo only)
└──────────┬─────────────┘
           │
   ┌───────▼────────┐
   │ Python ELT     │  extract/ + load/
   │ (idempotent)   │
   └───────┬────────┘
           │
   ┌───────▼────────┐
   │ raw schema     │  append-only
   └───────┬────────┘
           │
   ┌───────▼────────┐
   │ dbt staging    │  cleaned, typed, PII hashed
   └───────┬────────┘
           │
   ┌───────▼────────┐
   │ dbt marts      │  dim_/fact_ + profit marts
   └───────┬────────┘
           │
   ┌───────▼────────┐
   │ Power BI       │  phase-gated pages
   └────────────────┘
```

## 5. Dashboards (Power BI)

The Overview page is shown at the top of this README; the full report is six pages. Pages activate only when their source data is loaded:

| Page | Activates after |
|---|---|
| Executive Overview (sales) | Phase 4 |
| Executive Overview (with profit cards) | After Phase 3 cost enrichment + Phase 4 |
| Product Performance | Phase 4 |
| Country / Market Performance | Phase 4 |
| Customer / Repeat Purchase (hashed email) | Phase 4 |
| Fulfillment / Operations | Phase 5 |
| Website Behavior / GA4 Funnel | Phase 6 |
| Landing Page Performance | Phase 6 |
| Marketing (paid ROAS/MER/CAC) | **Optional Future only** |

## 6. Tech Stack

| Layer | Choice |
|---|---|
| Language (extract/load) | Python 3.11 |
| Storage | PostgreSQL 16 in Docker |
| Transforms | dbt-core + dbt-postgres |
| GA4 source | BigQuery |
| BI | Power BI Desktop |
| Version control | Git + GitHub |

## 7. Roadmap (revised)

| Phase | Outcome |
|---|---|
| 0 — Setup, Privacy, Source Audit | Postgres, dbt, `.gitignore`, site config, audit notes |
| 1 — WooCommerce API Raw Ingestion + **Payload Audit** | `raw.woo_*` per site + `docs/WOO_PAYLOAD_AUDIT.md` |
| 2 — dbt Staging + Core Marts | Sales/orders/products/customers/refunds in marts |
| 3 — **Manual Cost Enrichment** | COGS + design fee from sheet → `fact_order_cost`; profit marts become possible |
| 4 — Power BI MVP | Sales + product + country + customer (+ profit if Phase 3 done) |
| 5 — Fulfillment Enrichment Dashboard | Supplier/tracking → `fact_fulfillment`; Fulfillment page |
| 6 — GA4 BigQuery Modeling | Events → sessions → funnel; behavior pages |
| Optional Future — Ads & Attribution | Activated only if ads ever run |
| 7 — Synthetic Sample + Portfolio Polish | Fully synthetic public dataset, write-up, screenshots |

See [docs/ROADMAP.md](docs/ROADMAP.md) for detail.

## 8. Current Status

- [x] **Phase 0** — Docker/Postgres schemas, dbt project, privacy guards, `config/sites.yaml`, 7 seeds, Maven data dictionary translated (`docs/MAVEN_DATA_DICTIONARY.md`)
- [x] **Phase 1** — WooCommerce raw ingestion (incremental + idempotent) and the payload audit that locks the variant parser, payment-fee parser, and refund grain (`docs/WOO_PAYLOAD_AUDIT.md`)
- [x] **Phase 2** — dbt staging + core marts: orders, order items, products, customers, refunds, conformed dimensions
- [x] **Phase 3** — manual cost enrichment → `fact_order_cost`, profit marts, and the `recon_*` drift models
- [ ] **Phase 4** — Power BI MVP *(in progress: semantic model + report pages built, dashboard polish ongoing)*
- [ ] **Phase 5** — fulfillment enrichment → `fact_fulfillment`
- [ ] **Phase 6** — GA4 BigQuery modeling *(audit-gated: ≥85% `transaction_id` match required before attribution is enabled)*
- [ ] **Phase 7** — synthetic public dataset + portfolio polish

## 9. Privacy / Ethics

**Hard rules:**

- Real `Order Management.csv` and any real Woo extracts are listed in `.gitignore` — they live only on local disk.
- **Manual CSV PII rule:** For the manual Order Management CSV, unnecessary PII columns such as `Name`, `Email`, `Phone`, and `Ship to` are dropped **before** loading into `raw.csv_order_management`. Therefore `raw.csv_order_management` is **not** a byte-for-byte copy of the full sheet; it is a private raw operational extract with PII removed at ingestion. Tracking IDs and fulfillment URLs may be loaded to raw but **must** be hashed before staging/marts.
- Raw Woo customer data **never leaves the `raw` schema unhashed**. dbt staging hashes emails (SHA-256 with `PII_SALT`) and drops names/phones/addresses.
- The **public repo ships only a fully synthetic dataset** (plus the Maven sample where useful). No sanitized real-customer data, ever.
- BigQuery service account JSON, Woo consumer keys, and ads tokens live in `.env` (gitignored), never in source.
- **`config/sites.yaml` holds no secrets and no live endpoints** — the storefront URL and credentials are referenced by env-var *name* (`base_url_env` / `key_env` / `secret_env`) and resolved at runtime. Regression tests in `tests/test_site_config_matches_seed.py` fail the build if a literal URL is ever committed.
- The Power BI `.pbix` is gitignored because Import mode embeds a full data extract; only the TMDL text project is tracked.
- All websites use **guest checkout** — customer linkage is via SHA-256(normalized billing email + `PII_SALT`). Known caveats: one person/two emails counts as two customers; typo emails create separate customers; shared inbox counts as one.

See [docs/DATA_AUDIT.md](docs/DATA_AUDIT.md) for the PII inventory.

## 10. Running It Locally

Requires Docker, Python 3.11, and (for the dashboard) Power BI Desktop.

```bash
cp .env.example .env          # then fill in POSTGRES_*, WOO_FOS_*, PII_SALT
docker compose up -d postgres # Postgres 16
pip install -r requirements.txt

python -m src.extract.woo_api --apply-ddl   # land raw.woo_* (needs live Woo credentials)

cd dbt
dbt deps && dbt seed && dbt build           # raw → staging → marts, with tests
dbt docs generate && dbt docs serve         # lineage graph

pytest -q                                   # 90 tests, no database required
```

`PII_SALT` must be generated once and backed up offline — customer linkage is by hashed email, so losing the salt breaks every historical customer join.

Open `powerbi/ecommerce_analytics.pbip` in Power BI Desktop to load the semantic model against your local Postgres.

## 11. Documentation Index

**Design & specs**
- [docs/PROJECT_PLAN.md](docs/PROJECT_PLAN.md) — scope, site config, phased plan
- [docs/DATA_MODEL.md](docs/DATA_MODEL.md) — schemas, grains, profit formula
- [docs/PIPELINE_DESIGN.md](docs/PIPELINE_DESIGN.md) — EL design + dbt layout
- [docs/METRICS_DEFINITION.md](docs/METRICS_DEFINITION.md) — metric and DAX definitions
- [docs/METRIC_CHANGES.md](docs/METRIC_CHANGES.md) — versioned metric decisions and why they changed
- [docs/DASHBOARD_SPEC.md](docs/DASHBOARD_SPEC.md) — pages + data-quality gating
- [docs/ROADMAP.md](docs/ROADMAP.md)

**Audits & gates**
- [docs/WOO_PAYLOAD_AUDIT.md](docs/WOO_PAYLOAD_AUDIT.md) — **Phase 1 gate** (locks variant/payment-fee parsers, refund grain)
- [docs/GA4_BIGQUERY_AUDIT.md](docs/GA4_BIGQUERY_AUDIT.md) — **Phase 6 gate** (attribution match rate)
- [docs/DATA_AUDIT.md](docs/DATA_AUDIT.md) — PII inventory

**Power BI**
- [powerbi/BUILD_GUIDE.md](powerbi/BUILD_GUIDE.md) — model + report build notes
- [powerbi/CAPSTONE_BUILD_GUIDE.md](powerbi/CAPSTONE_BUILD_GUIDE.md) — current dashboard build

**Other**
- [TASKS.md](TASKS.md) — authoritative checkbox-level task list
- [docs/learning/](docs/learning/) — Vietnamese-language write-ups explaining each layer of the build

## 12. License

[MIT](LICENSE). The code and models are open; **no real store data is included in this repository** — see §9.
