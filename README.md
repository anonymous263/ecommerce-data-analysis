# Ecommerce Analytics Warehouse — WooCommerce → dbt → Power BI

An end-to-end analytics warehouse for print-on-demand WooCommerce stores. Python pulls orders from the WooCommerce REST API and the operator's cost spreadsheet, dbt turns them into a Kimball star schema on Postgres, and a Power BI report answers the question the store's own admin panel cannot: **what actually makes money after COGS, design fees, and payment fees?**

![Executive Overview dashboard — KPI cards, monthly revenue and profit trend, top markets, and a revenue-to-profit waterfall](powerbi/screenshots/overview.png)

<sub><b>Executive Overview.</b> The bridge on the lower right decomposes revenue into COGS, design fee, and payment fee to land on contribution profit. Note that <i>Net rev</i> ($72.1K) exceeds <i>Product Revenue</i> ($55.4K) — the customer shipping charge is counted as revenue, since the supplier's fulfilment fee is already inside COGS.</sub>

---

## The questions it answers

- Which products and markets are profitable **after** every cost, not just at gross revenue?
- How much of each revenue dollar survives to profit — and which line item eats the most?
- Which markets carry the store, and are they stalling?
- How many customers come back, and what is a repeat customer worth?
- Where does the warehouse disagree with the spreadsheet the business actually runs on?

## Architecture

```
WooCommerce REST API ─┐
                      ├─→  Python EL  ─→  Postgres  ─→  dbt  ─→  Power BI
Cost spreadsheet (CSV)┘   extract/load     raw        staging     .pbip
                          only                        + marts     (TMDL)
```

The split is deliberate and strictly enforced: **Python only lands data, dbt owns every transform.** The extractors copy API payloads verbatim into append-only `raw` tables — every row carries `site_code`, `extracted_at`, and the untouched `_payload` JSONB. Typing, currency conversion, hashing, joins, cost allocation, and the profit calculation all happen in dbt, where they are version-controlled and testable.

## Data model

A Kimball star schema across `staging` → `marts_core` / `marts_operations` / `marts_recon`.

| | |
|---|---|
| **Facts** | `fact_order` (order grain) · `fact_order_item` (line grain) · `fact_refund` · `fact_order_cost` |
| **Conformed dimensions** | `dim_date` · `dim_product` · `dim_country` · `dim_customer_anonymized` · `dim_payment_method` · `dim_site` |
| **Marts** | `mart_order_profit` · `mart_product_profit` · `mart_customer_summary` |
| **Reconciliation** | six `recon_*` models diffing the warehouse against the source spreadsheet |

Every row carries `site_code` / `site_sk`, so the model is multi-store from the ground up; an order's natural key is `site_code + woo_order_id`.

**Revenue lives in exactly one place per grain.** Product revenue exists only on `fact_order_item`; the customer shipping charge exists only on `fact_order`. `fact_order` deliberately has *no* product-revenue column — that single constraint is what stops an order × item join from silently double-counting revenue, the most common way this kind of model goes wrong.

## Tech stack

| Layer | Choice |
|---|---|
| Extract / load | Python 3.11 · httpx · SQLAlchemy · pandas |
| Storage | PostgreSQL 16 (Docker) |
| Transforms | dbt-core 1.10 + dbt-postgres |
| BI | Power BI Desktop (`.pbip` / TMDL) |
| Tests | pytest (90 tests) · dbt schema + singular tests · GitHub Actions |

## Running it locally

Requires Docker, Python 3.11, and Power BI Desktop for the report.

```bash
cp .env.example .env          # fill in POSTGRES_*, WOO_<SITE>_BASE_URL/_KEY/_SECRET, PII_SALT
docker compose up -d postgres
pip install -r requirements.txt

python -m src.extract.woo_api --apply-ddl   # land raw.woo_* (needs live store credentials)

cd dbt
dbt deps && dbt seed && dbt build           # raw → staging → marts, with tests
dbt docs generate && dbt docs serve         # lineage graph

pytest -q                                   # hermetic: no database, no credentials
```

`PII_SALT` is generated once and must be backed up offline — customer linkage is by hashed email, so losing it breaks every historical customer join.

Open `powerbi/ecommerce_analytics.pbip` in Power BI Desktop to point the semantic model at your local Postgres.

## Repository layout

```
src/extract/     WooCommerce API + cost-spreadsheet extractors
src/load/        engine, batched idempotent upserts
src/utils/       site config, HTTP retry, logging
sql/ddl/         raw-schema DDL
dbt/models/      staging/ + marts/{core,operations,reconciliation}
dbt/seeds/       sites, FX rates, country map, payment fees
dbt/macros/      PII hashing, schema naming
powerbi/         .pbip project (TMDL), DAX measures, screenshots
tests/           pytest suite
```

## License

[MIT](LICENSE). No real store data is included in this repository.
