# Project Plan — Ecommerce Data Analysis (WooCommerce-first + Manual Cost Enrichment)

> Private business warehouse first, portfolio second. WooCommerce REST API owns revenue and orders. The manual Order Management sheet owns cost enrichment: COGS, design fee, and operational fulfillment fields. CSV `Shipping` is customer shipping charge for reconciliation only, not supplier shipping cost. GA4 BigQuery owns behavior. Ads is optional future, not part of MVP.

---

## 1. Mindset & Business Thinking

**1.1 — Start from the decision, not from the data.**
Every metric on a dashboard must change behavior. If a chart can't change a decision, cut it.

**1.2 — Trust the grain.**
Each fact has one grain. Write it down. Never deviate.

**1.3 — Pick a source of truth and stick to it.**
WooCommerce owns revenue and orders. The CSV owns cost and operational enrichment. GA4 owns behavior. They cooperate. They don't compete.

**1.4 — Reconciliation > prettiness.**
CSV revenue ≠ Woo revenue. GA4 purchases ≠ Woo orders. The job is to know *why* and surface the right number for the right question.

**1.5 — Business warehouse first, portfolio second.**
The system must run on real data, privately. The public portfolio is a separate, fully synthetic dataset.

---

## 2. Business Questions This Project Must Answer

- Which products / topics / sites drive the most **contribution profit** (after COGS + design fee + payment fee + shipping)?
- Which countries / markets buy most at the best margin?
- Where do visitors drop off in the funnel?
- Which suppliers fulfill fastest, and which carriers cause delivery exceptions?
- Repeat customer behavior under guest checkout?

---

## 3. Data Source Analysis

| Source | Owns | Trust | Phase |
|---|---|---|---|
| **WooCommerce REST API** | Orders, items, products, customers, coupons, refunds/cancellations, status | High | **1 (source of truth)** |
| **GA4 BigQuery export** | Sessions, events, funnel, landing pages, traffic source | Structurally high; behavioral data ≠ orders | **6 (source of truth for behavior)** |
| **Manual Order Management CSV / Sheet** | **COGS (incl. supplier fulfillment/shipping fee), design fee, supplier, tracking ID, fulfillment URL, carrier, "Check Sent", notes**; CSV `Shipping` column = customer shipping charge (reconciliation only, not a cost) | Medium — manual entry, audited | **3 (cost enrichment), 5 (fulfillment)** |
| Maven Fuzzy Factory sample | Practice / demo only | n/a | 0 practice, 7 demo |
| Ads platforms | Spend / impressions / clicks | High when running, but **none currently** | **Optional Future** |

**Realities:**
- WooCommerce has been confirmed working in n8n.
- POD variants are produced via the **WooCommerce Custom Product Addons by Acowebs** plugin — variant info likely lives in `line_items[].meta_data`, but the exact keys are unknown until [WOO_PAYLOAD_AUDIT.md](WOO_PAYLOAD_AUDIT.md) is executed in Phase 1.
- The site uses a **payment gateway wrapper plugin**, not the official Stripe/PayPal plugins, so payment fee fields may not match official gateway schemas. Payment fee source is tagged on `fact_order.payment_fee_source` as `api_exact` / `plugin_parser` / `seed_estimate` / `missing`.
- All sites use **guest checkout**; `customer_id` in Woo will typically be `0`. Customer identity is reconstructed from hashed billing email.
- GA4 ecommerce is tracked via **GTM + PixelYourSite** — whether `transaction_id` equals the Woo `order_id` is unknown until [GA4_BIGQUERY_AUDIT.md](GA4_BIGQUERY_AUDIT.md) is executed in Phase 6.
- The CSV `Shipping` column is the **customer shipping charge**, not supplier shipping cost. Supplier fulfillment/shipping fee is included in CSV `CoGS`. Contribution profit therefore does **not** subtract a separate shipping cost.

---

## 4. Data Warehouse Design Approach

**Kimball-style star schema in PostgreSQL**, transformed by **dbt**.

Postgres schemas:

| Schema | Owner | Purpose |
|---|---|---|
| `raw` | Python ELT | Exact source copy, append-only |
| `staging` | dbt | Cleaned, typed, deduped, PII hashed |
| `marts_core` | dbt | `dim_*` and revenue/order/customer facts |
| `marts_marketing` | dbt | GA4 facts and (optional) ads facts |
| `marts_operations` | dbt | `fact_order_cost`, `fact_fulfillment`, supplier |
| `marts_recon` | dbt | Reconciliation views (CSV vs Woo, GA4 vs Woo) |

Every transformation between `raw` and a mart is idempotent dbt SQL.

See [DATA_MODEL.md](DATA_MODEL.md).

---

## 5. Pipeline Design (overview)

Four extract/load pipelines, all transformed by one dbt graph:

1. **WooCommerce pipeline** — Python pulls per-site orders/items/products/customers/refunds/coupons via REST API → `raw.woo_*`.
2. **Manual cost/fulfillment pipeline** — periodic CSV load of the Order Management sheet → `raw.csv_order_management` → split into `stg_manual_order_cost_enrichment` and `stg_manual_fulfillment_enrichment`.
3. **GA4 pipeline** — Python pulls `events_YYYYMMDD` via BigQuery → `raw.ga4_*`.
4. **Ads pipeline** — optional future, not part of MVP.

Detail in [PIPELINE_DESIGN.md](PIPELINE_DESIGN.md).

---

## 6. Dashboard Design (overview)

Phase-gated pages, see [DASHBOARD_SPEC.md](DASHBOARD_SPEC.md).

The biggest design rule: **profit metrics activate only after Phase 3 cost enrichment is loaded.** Before that, the dashboard ships as a "sales-only" view with profit cards hidden or labeled "approximate (seeds only)".

---

## 7. Technical Requirements

### 7.1 Environment
- Python 3.11+, `uv` or `pip`
- Docker Desktop
- PostgreSQL 16 in Docker
- dbt-core + dbt-postgres
- Google Cloud SDK + service account (Phase 6)
- Power BI Desktop
- Git + GitHub

### 7.2 Python packages
`pandas`, `polars`, `pyarrow`, `sqlalchemy`, `httpx`, `python-dotenv`, `pytest`, `google-cloud-bigquery`, `db-dtypes`, `dbt-core`, `dbt-postgres`, `ruff`, `black`, `pre-commit`.

### 7.3 Secrets / config
- `.env` (gitignored) with `POSTGRES_*`, `WOO_<SITECODE>_KEY` / `_SECRET`, `PII_SALT`, `GOOGLE_APPLICATION_CREDENTIALS`.
- `.env.example` committed as template.
- Multi-site config: `config/sites.yaml` + `dbt/seeds/dim_site_seed.csv` (see §8).

---

## 8. Multi-Site Configuration

Every raw/staging/mart row carries `site_code` (text) and/or `site_sk` (int). Order natural key = `site_code + woo_order_id`.

**`config/sites.yaml`** (Python ELT):
```yaml
sites:
  - site_code: FOS
    site_name: Fashion Open Studio
    base_url: https://fashionopenstudio.com
    key_env: WOO_FOS_KEY
    secret_env: WOO_FOS_SECRET
    default_currency: USD
    timezone: UTC                    # source WordPress/WooCommerce site timezone
    reporting_timezone: Asia/Bangkok # business/dashboard reporting timezone
    is_active: true
  # add other sites here
```

**`dbt/seeds/dim_site_seed.csv`** (dbt):
```
site_code,site_name,domain,default_currency,timezone,reporting_timezone,is_active
FOS,Fashion Open Studio,fashionopenstudio.com,USD,UTC,Asia/Bangkok,true
```

Both files must list the same sites and timezone fields. `timezone` is the source site's WordPress/WooCommerce timezone. `reporting_timezone` is the business/dashboard timezone used for internal reporting.

For FOS, the source WordPress/WooCommerce timezone is UTC. Do not use `Europe/London` for FOS because London observes daylight saving time and may become UTC+1.

---

## 9. Learning Requirements (per phase)

| Phase | What I'll learn |
|---|---|
| 0 | Postgres + dbt scaffolding, PII boundaries, multi-site config |
| 1 | REST API pagination, idempotent upsert, payload auditing |
| 2 | dbt sources, models, tests, star schema discipline, surrogate keys, FX modeling |
| 3 | Joining enrichment safely, cost allocation methods, coverage metrics |
| 4 | Power BI semantic model, DAX, conditional measure display |
| 5 | Operational analytics with conditional data |
| 6 | BigQuery, `UNNEST`, sessionization, attribution audit |
| Optional Future | Ads APIs, attribution model |
| 7 | Synthetic data generation, anonymization, portfolio storytelling |

---

## 10. Milestones

| Milestone | Definition of done |
|---|---|
| M0 | Postgres + dbt running, privacy guards in place, site config seeded |
| M1 | Per-site `raw.woo_*` loaded; `docs/WOO_PAYLOAD_AUDIT.md` complete |
| M2 | dbt `marts_core` populated with sales/orders/customers/refunds |
| M3 | `fact_order_cost` populated from manual CSV; profit marts available |
| M4 | Power BI MVP dashboard (sales + profit + product + country + customer) |
| M5 | `fact_fulfillment` populated; fulfillment dashboard live |
| M6 | GA4 events → sessions → funnel; behavior pages live |
| (Opt) | Ad spend + attribution live |
| M7 | Synthetic public dataset + published repo + write-up |

---

## 11. Final Deliverables

- This documentation set, kept current.
- Reproducible pipeline: `python -m src.cli extract-woo && python -m src.cli load-csv-order-management && dbt build`.
- A populated PostgreSQL warehouse + a BigQuery GA4 dataset.
- A dbt project with models, tests, docs.
- A `.pbix` Power BI file.
- A short portfolio write-up with screenshots + 3 decision case studies.
- A **fully synthetic** public sample dataset that mimics the real schema, generated by a script — no sanitized real data.
