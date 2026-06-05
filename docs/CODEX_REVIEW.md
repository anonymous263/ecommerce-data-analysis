# Codex Review Report

## 1. Executive Summary

The project plan is good and directionally fit for a real WooCommerce/POD analytics portfolio project. The documentation shows strong awareness of business questions, dimensional modeling, GA4 reconciliation, and PII risk.

The project is not ready to move straight into Phase 1 coding without a few revisions. The biggest risks are grain ambiguity in `Order Management.csv`, possible double-counting of revenue/profit across `fact_order` and `fact_order_item`, and privacy exposure because the real order CSV is currently in the repository root while `.gitignore` does not exist yet.

Assumption: this review is based only on the local files present on June 4, 2026. No live WooCommerce, GA4 BigQuery, Ads, or Power BI files were inspected.

## 2. What Looks Strong

- The business questions are mostly grounded in actual owner decisions: product selection, country performance, margin, supplier delays, funnel drop-off, and campaign efficiency.
- The Raw -> Staging -> Mart -> Power BI architecture is appropriate for a beginner-friendly analytics engineering project.
- The storage progression from SQLite to Postgres, with optional BigQuery for GA4, is reasonable.
- The docs correctly warn that GA4 will not reconcile perfectly to WooCommerce and that historical GA4 BigQuery backfill is not available before export start.
- The model separates order, order item, refund, fulfillment, GA4 session/event, and ad spend facts instead of forcing everything into one table.
- The dashboard spec is decision-oriented and not just a list of charts.
- Privacy is treated as a first-class topic in the docs, especially for names, emails, phones, addresses, fulfillment links, and tracking IDs.
- The roadmap is phased and avoids premature orchestration.

## 3. Key Risks and Gaps

- `Order Management.csv` needs a firm grain decision before coding. The inspected file has 10 loaded product rows, seven distinct order codes, and three repeated `Project + Order Code` combinations. Three rows with product names have blank quantity and financial fields. If those blanks are forward-filled into item rows, item revenue/profit can be overstated.
- The docs define revenue primarily from `fact_order_item.line_revenue_usd`, but the real CSV appears to store financial values at the priced/order row level, not reliably on every product row. Phase 1 must decide whether item-level financials are truly available or whether order-level financials should remain in `fact_order`.
- `fact_order` and `fact_order_item` both contain revenue, COGS, and profit-style fields. This can create double-counting in Power BI if both facts are exposed without strict measures.
- The real CSV is currently at the project root. If git is initialized and `git add .` is run before `.gitignore`, PII may be committed accidentally.
- `.gitignore`, `.env.example`, `dim_site_seed.csv`, and `dim_supplier_seed.csv` are not present yet, although the docs and tasks depend on them.
- The plan says to move `Order Management.csv` and the sample folder into `data/raw/`, but the root README also documents them at the root. Pick one convention before implementation.
- GA4 is planned well, but still abstract. Phase 3 needs concrete project IDs, property/site mapping, dataset names, timezone rules, and validation that `transaction_id` equals WooCommerce order ID per site.
- Ads attribution is intentionally later, but UTM governance and campaign mapping should be specified before ads data arrives.
- Public portfolio safety should prefer fully synthetic/anonymized demo data, not hashed real customer-level data. Hashes are still pseudonymous and can be risky in a small dataset.

## 4. Data Source Review

### `Order Management.csv`

Inspected safely without printing PII values.

- File size: 5,911 bytes.
- Raw shape including the two non-data summary rows: 12 rows x 39 columns.
- Loaded shape using the planned `skiprows=[1,2]`: 10 rows x 39 columns.
- Nonblank loaded rows: 10.
- Distinct `Order Code` values: 7.
- Duplicate `Project + Order Code` rows among nonblank keys: 3, which confirms multi-product or multi-line order behavior.
- Duplicate `Project + Order Code + Product name + Type` rows: 0 in the inspected file.
- The column ` Shipping Company ` has leading/trailing spaces.
- Sensitive or potentially sensitive columns are present by name: `Name`, `Ship to`, `Email`, `Phone`, `Tracking ID`, `Tracking Deliver URL`, `Fulfill URL`, `Order URL`, and `Product URL`.
- The file contains currency/percent text fields that need parsing: `Items Subtotal`, `Shipping`, `Total`, `Fee`, `Payout`, `Revenue`, `CoGS`, `Design fee`, `Profit`, `ROI`, and `Profit Margin`.
- The source has an accented column name: `Típs/Coupon`. Code should normalize column names while preserving a raw copy.
- `Note` and `Total New Order` are blank in all loaded rows inspected.
- The file has two currencies and three countries in the inspected sample.

Main implication: Phase 1 should start with an audit notebook that classifies each column as order-level, item-level, fulfillment-level, customer-level, or private-only. Do not write the item mart until the blank financial rows are understood.

### `E-commerce data sample/`

The sample data is structurally clean and suitable for SQL/modeling practice.

| File | Rows | Columns | Notes |
|---|---:|---:|---|
| `orders.csv` | 32,313 | 8 | No duplicate `order_id`; no nulls. |
| `order_items.csv` | 40,025 | 7 | No duplicate `order_item_id`; 7,712 orders have multiple items. |
| `order_item_refunds.csv` | 1,731 | 5 | No duplicate refund IDs; no repeated refund per item in inspected data. |
| `products.csv` | 4 | 3 | Very small product dimension; fine for practice, weak for realistic product analytics. |
| `website_sessions.csv` | 472,871 | 9 | UTM and referrer nulls are expected; no duplicate session IDs. |
| `website_pageviews.csv` | 1,188,124 | 4 | No duplicate pageview IDs; 16 distinct pageview URLs. |
| `[Đọc cái này trước] Tài liệu Data Dictionary.docx` | n/a | n/a | Contains six tables and should be summarized into `docs/MAVEN_DATA_DICTIONARY.md`. |

Relationship checks passed:

- All orders match a website session.
- All order primary products match products.
- All order items match orders and products.
- All refunds match orders and order items.
- All pageviews match website sessions.

Main implication: Maven can be used as a safe public/practice dataset, but it should be kept separate from the real POD mart because its business model, products, and channels are not the same.

### Planned GA4 BigQuery Source

No local GA4 data or credentials were present. The docs correctly treat GA4 as a core planned source for funnel, landing page, traffic, campaign, and conversion analysis.

Before GA4 coding, confirm:

- One GA4 property/dataset per site or a documented multi-site mapping.
- Export start date and earliest available `events_YYYYMMDD`.
- Whether `purchase` events contain a stable WooCommerce order ID in `transaction_id`.
- Whether ecommerce `items` are populated for `view_item`, `add_to_cart`, `begin_checkout`, and `purchase`.
- Timezone handling between GA4 UTC dates and WooCommerce/site local dates.
- Whether page URLs contain query strings or identifiers that should be stripped before mart/public use.

## 5. Data Model Review

The proposed star schema is mostly appropriate for Power BI. The grains are explicitly listed, which is the best part of the model.

Recommended corrections:

- Decide whether `fact_order_item` can own `line_revenue_usd`, `line_cogs_usd`, and `line_profit_usd` for the real CSV. If not, Phase 1 should put financials in `fact_order` and keep `fact_order_item` to quantity/product attribution only until line allocation is defined.
- Avoid exposing additive revenue/profit measures from both `fact_order` and `fact_order_item`. Define one official measure path per metric.
- Add `order_status_sk` or a small status mapping only if statuses become messy. For Phase 1, a cleaned text status is enough.
- `dim_customer_anonymized` should not store `total_orders` and `total_revenue_usd` as dimension attributes in the first version. Those are aggregate measures and can become stale. Use a customer aggregate mart later if needed.
- `fact_fulfillment` is a good target, but current data likely lacks reliable ship/deliver dates. Start with `check_sent`, carrier, supplier identifiers, and backlog age from order date/status.
- For GA4 facts, hash or protect `user_pseudo_id` before any public extract. It is not direct PII, but it is still user-level tracking data.
- Add a small mapping table for country normalization (`UK` -> `GB`) and channel grouping. Do not hard-code those mappings only inside transformation code.

## 6. Metrics Review

The metric list is strong, but several definitions need tighter source ownership.

- Revenue, net revenue, gross profit, contribution profit, and margin must specify whether they are sourced from order-level or item-level facts in Phase 1.
- Contribution profit is the right north-star POD profitability metric, but shipping cost needs to distinguish shipping charged to customer from actual supplier/carrier shipping cost.
- `ROI = Profit / COGS` is useful for POD operations but should be labeled as "POD ROI" or "Goods-cost ROI" to avoid confusion with marketing ROI.
- Refund rate needs both item-level and order-level versions if the dashboard will answer product quality and owner-level questions.
- CAC should stay disabled until reliable new-customer identity exists. Hashed email may be enough for a private model, but not for a public demo.
- ROAS needs a documented attribution model before it appears in Power BI. MER can appear earlier because it does not require session/order attribution.
- Funnel metrics should consistently use session-level booleans to avoid counting multiple events from one session as multiple users moving through the funnel.
- Add sample-size guards for country, product, and campaign metrics. The dashboard spec mentions this for countries; apply it more broadly.

Missing or useful POD metrics:

- Contribution profit per order.
- Contribution profit per item.
- Shipping charged vs shipping/COGS cost gap.
- Processing backlog age.
- Supplier SLA breach count.
- Cancellation rate.
- Product/design first-seen and last-seen sales.
- Repeat purchase rate only after customer linkage is trustworthy.

## 7. Pipeline Review

The MVP CSV pipeline is feasible for a beginner if it starts with audit-first code and a small warehouse target.

Recommended Phase 1 pipeline shape:

- Load raw CSV exactly as-is into a private raw table or raw file snapshot.
- Build `stg_order_management_rows` with cleaned column names, typed dates, parsed currency/percent fields, and PII handling.
- Build separate `stg_orders` and `stg_order_items` only after row-grain classification is verified.
- Create quarantine outputs for rows with invalid dates, unparseable money, unknown country codes, missing order keys, or impossible negative values.
- Write tests before broad transforms: currency parser, percent parser, country mapper, PII hasher, key uniqueness, and revenue reconciliation.

WooCommerce API pipeline:

- The high-watermark and pagination plan is realistic.
- Use `date_modified_gmt` or a clearly timezone-aware field when possible.
- Store raw API responses or normalized raw tables with extraction timestamp.
- Do not advance the watermark after partial failure.

GA4 BigQuery pipeline:

- The plan is realistic, but event-level data can become large. For a laptop portfolio workflow, consider extracting only the needed columns/date range or materializing session/page/ecommerce marts in BigQuery before importing to local storage.
- Intraday tables are mutable. Keep them separate from finalized daily tables.
- Traffic source logic should be session-scoped and tested against a small sample.

Ads pipeline:

- The future daily ad spend grain is correct.
- Add UTM naming rules and a campaign mapping table before trying to join spend to GA4 sessions.
- Keep MER as the first marketing efficiency metric; defer precise ROAS until attribution coverage is measurable.

Cross-cutting:

- Logging and `pipeline_runs` are good ideas.
- Add a `pipeline_state` table earlier than Phase 3 if Woo/GA4 incremental work begins.
- For Phase 1, simple pytest + SQL assertions are enough; do not add Great Expectations until the pipeline has stable tables.

## 8. Dashboard Review

The dashboard pages support real decision-making. The best pages for Phase 1 are:

- Executive Overview.
- Product Performance.
- Country / Market Performance.

Recommended adjustments:

- Hide Marketing, Website Behavior, Landing Page, and Customer pages until GA4/ads/customer linkage exist. Empty pages will weaken the portfolio.
- The first dashboard should reconcile to the source CSV before adding many visuals.
- Use one official revenue/profit measure path and document it in DAX measure descriptions.
- Add a small "Data Health" area or tooltip: last refresh date, source file name, row count, orders loaded, parsing errors, and PII removed.
- The Product page should separate product title/type from design topic. Design topic may need manual tagging at first.
- The Operations page should be limited until ship/deliver dates exist. Backlog and `Check Sent` can be useful earlier.

## 9. Privacy and Portfolio Safety Review

The privacy intent is good, but the current file placement is risky.

Must fix before any git commit:

- Add `.gitignore` before `git init` / first commit.
- Ignore `Order Management.csv`, `data/raw/`, `.env`, service account JSON, Power BI backups, local databases, logs, and cache folders.
- Move real raw data into an ignored private raw location after `.gitignore` exists.
- Keep only sanitized sample data in committed paths.

Additional safety notes:

- Hashing emails/tracking IDs is pseudonymization, not full anonymization. Do not publish hashed row-level real customers in a public repo.
- Drop address, phone, tracking URL, fulfillment admin URL, and order admin URL from staging outputs intended for portfolio/demo use.
- Strip query strings from GA4 `page_location` before public marts because URLs can contain identifiers.
- Use a project-local salt stored outside git if hashing is needed for private analysis.
- Generate synthetic public demo orders instead of modifying real orders when possible.

## 10. Documentation Consistency Check

Issues to revise:

- `README.md` and `TASKS.md` reference root-level source files, while tasks also say to move them into `data/raw/`. Decide and document one canonical location.
- `DATA_AUDIT.md` describes the real CSV as having numbered columns through 37, but the inspected file has 39 physical columns because `Day`, `Month`, and `Year` are separate columns. The narrative is understandable but should be corrected to avoid implementation mistakes.
- `DATA_AUDIT.md` and `TASKS.md` suggest forward-filling order header fields onto child rows. That needs a warning: do not forward-fill financial fields into child item rows unless the intended allocation logic is defined.
- `PROJECT_PLAN.md` lists `.env.example` and config needs, but those files are not present.
- `ROADMAP.md` says Phase 0 output includes seed CSVs and `.gitignore`, but they are absent.
- `PIPELINE_DESIGN.md` names `raw`, `staging`, and `mart` layers, while table naming uses prefixes like `raw_*` in SQLite. That is fine, but SQLite cannot have real schemas; document that prefixes are the SQLite substitute.
- `METRICS_DEFINITION.md` references `docs/METRIC_CHANGES.md` as TBD. That is fine later, but do not block Phase 1 on it.
- The docs are beginner-friendly, but some sections duplicate the same architecture and roadmap. This is acceptable now; later, shorten README and keep detailed rules in docs.

## 11. Recommended Revisions Before Coding

### Must fix before Phase 1

1. Add `.gitignore` before initializing or committing to git.
2. Decide canonical data locations for private raw data and public sample data.
3. Update the CSV grain rules: which fields are order-level, item-level, fulfillment-level, customer-level, and private-only.
4. Decide where official Phase 1 revenue/profit measures come from: `fact_order` or `fact_order_item`.
5. Add `dim_site_seed.csv` and `dim_supplier_seed.csv` or explicitly defer supplier SLA metrics.
6. Define PII handling outputs: what gets dropped, what gets hashed, and what never enters marts.

### Should fix soon

1. Add `.env.example`.
2. Create `docs/MAVEN_DATA_DICTIONARY.md` from the Vietnamese docx.
3. Add country and currency mapping seed files.
4. Add a small data quality checklist to `DATA_AUDIT.md`.
5. Add Power BI measure naming conventions.
6. Clarify Phase 1 SQLite schema prefixes versus future Postgres schemas.

### Nice to have later

1. Add `config/sites.yaml`.
2. Add `config/suppliers.yaml` or seed CSV with SLA.
3. Add `docs/METRIC_CHANGES.md` when metrics first change.
4. Add `powerbi/measures/`, `powerbi/themes/`, and `powerbi/screenshots/` when the PBIX exists.
5. Add a synthetic portfolio dataset generator.

## 12. Recommended Phase 1 Implementation Plan

1. First notebook: `notebooks/00_inventory.ipynb`
   - List all files, row counts, columns, blank counts, and detected sensitive columns.
   - Verify `Order Management.csv` row patterns without printing PII.

2. First transformation module: `src/extract/csv_orders.py`
   - Implement `load_order_management(path) -> DataFrame`.
   - Preserve raw column names in the raw load.
   - Return a cleaned-column staging DataFrame only after explicit normalization.

3. First utility modules:
   - `src/utils/parse.py` for money and percent parsing.
   - `src/utils/privacy.py` or `src/utils/hashing.py` for PII drop/hash logic.
   - `src/utils/mapping.py` for country/currency/status mapping.

4. First tests:
   - `tests/test_parse.py`: currency and percent parsing.
   - `tests/test_privacy.py`: PII fields are absent or hashed in public/staging output.
   - `tests/test_order_grain.py`: `Project + Order Code` uniqueness for order table and no accidental revenue duplication across item rows.
   - `tests/test_reconciliation.py`: staged revenue/profit reconciles to the source rows selected as financial-bearing rows.

5. First database tables:
   - `raw_orders_csv`.
   - `stg_order_management_rows`.
   - `dim_date`.
   - `dim_site`.
   - `dim_country`.
   - `dim_product`.
   - `fact_order`.
   - Add `fact_order_item` only after item financial/quantity logic is confirmed.

6. First Power BI MVP page:
   - Executive Overview only, with Revenue, Orders, AOV, Contribution Profit, Profit Margin, and a simple country/product split.
   - Add Product and Country pages after source reconciliation passes.

## 13. Suggested Acceptance Criteria for Phase 1

- `.gitignore` exists and protects private raw data before the first commit.
- `Order Management.csv` can be loaded with no PII printed to logs or notebook outputs.
- `stg_order_management_rows` has cleaned column names, typed dates, parsed numeric fields, normalized country codes, and explicit PII policy applied.
- `fact_order` has exactly one row per `site_code + order_code`.
- Revenue and profit in the database reconcile to the source CSV financial-bearing rows within a documented tolerance.
- No dashboard measure double-counts multi-line orders.
- At least five source orders are hand-checked against staged outputs.
- Unit tests cover parsers, PII handling, key uniqueness, and revenue reconciliation.
- SQLite database rebuild is idempotent from the local raw input.
- Power BI MVP has at least one working Executive Overview page backed by the SQLite marts.
- The dashboard includes a caveat that Phase 1 does not yet include GA4, WooCommerce API, ads spend, or reliable repeat-customer analysis.
