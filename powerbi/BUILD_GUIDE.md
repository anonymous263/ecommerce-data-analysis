# Power BI Build Guide — Phase 4 MVP

A click-by-click guide for a solo analyst to assemble the Phase 4 Power BI Desktop dashboard from the pre-authored DAX measure library (`powerbi/measures/dax_measures.txt`) and theme (`powerbi/themes/ecommerce_theme.json`).

This guide assumes:
- Power BI Desktop is installed (recent monthly release).
- Postgres 16 is running in Docker (`ecommerce_postgres`, healthy) with all `marts_*` schemas built (`dbt build` green).
- The Npgsql provider is available to Power BI (Power BI Desktop ships with the PostgreSQL connector; if prompted, install Npgsql).

Reference specs while building: `docs/DASHBOARD_SPEC.md` (pages + gating) and `docs/METRICS_DEFINITION.md` (every metric's formula, source, caveat). The DAX `Description` fields cross-link back to `METRICS_DEFINITION.md` — keep them intact.

---

## 0. Live data-quality state (read this first)

The tier-gating you wire up in Step 6 is driven by two live coverage numbers. As of the current build:

| Coverage | Live value | Tier | Effect on dashboard |
|---|---|---|---|
| Cost Coverage % (H1, revenue-order basis) | **98.79%** | GREEN (≥ 95%) | Profit visuals **shown**, **no** partial-coverage chip |
| Payment Fee Coverage % (H4, revenue-order basis) | **98.03%** | ≥ 80% | Payment-fee chip **NOT shown** (all-orders 79.50% is informational only) |

So in the finished MVP: profit cards and charts are **visible and fully untagged** — no partial-coverage chip and no payment-fee chip, because both coverages clear their thresholds on a revenue-order basis. Build and verify against that expected state.

---

## 1. Get Data — import from PostgreSQL

1. **Home → Get data → More… → Database → PostgreSQL database → Connect.**
2. Server: `localhost:5432` — Database: `ecommerce`.
3. **Data Connectivity mode: Import** (not DirectQuery). Click **OK**.
4. Authentication: **Database** tab → enter the Postgres user/password from your local `.env` (`POSTGRES_USER` / `POSTGRES_PASSWORD`). Do **not** hardcode these anywhere; Power BI stores them in its own credential store. Click **Connect**. If you get a TLS/encryption prompt for a local Docker instance, accept the non-encrypted local connection.
5. In the **Navigator**, tick exactly these 18 tables. The PostgreSQL connector shows a **flat list** with schema-prefixed display names (`marts_core fact_order_item`) — there are no expandable schema folders, and no way to import bare table names. That prefix is expected; step 7 removes it.

   - `marts_core fact_order`
   - `marts_core fact_order_item`
   - `marts_core fact_refund`
   - `marts_core mart_order_profit`
   - `marts_core mart_product_profit`
   - `marts_core mart_country_profit`
   - `marts_core mart_customer_summary`
   - `marts_core dim_date`
   - `marts_core dim_site`
   - `marts_core dim_country`
   - `marts_core dim_product`
   - `marts_core dim_customer_anonymized`
   - `marts_operations fact_order_cost`
   - `marts_recon recon_cost_coverage`
   - `marts_recon recon_payment_fee_coverage`
   - `marts_recon recon_csv_vs_dbt_revenue`
   - `marts_recon recon_csv_vs_dbt_profit`
   - `marts_recon recon_woo_vs_csv_shipping_charged`

   Do **not** tick `marts_core dim_payment_method` or `marts_recon recon_unmatched_csv_cost` — they exist in Postgres but nothing in the measure library reads them.

6. Click **Load** (not Transform Data — the dbt marts are already clean and typed). Wait for all 18 tables to import.

7. **Rename every table to strip the schema prefix** — required, not cosmetic. In the Data pane, right-click each table → **Rename** → delete the `<schema> ` prefix, leaving `fact_order_item`, `dim_country`, and so on. Names must be lowercase with underscores, matching `measures/dax_measures.txt` exactly (DAX table names are case-sensitive).

   DAX resolves tables by **model table name only** — it never sees Postgres schemas. The `Source{[Schema="marts_core", Item="fact_order_item"]}[Data]` navigation step inside each query is how Power Query fetches rows; it does not name the table. Skip this step and every measure fails with `Cannot find table 'fact_order_item'`.

   Renaming is safe at any point: it re-binds measures and relationships automatically and does not re-query Postgres.

> The three `recon_*` coverage/drift tables are tiny lookup tables. Load them, but do **not** relate them to the star. Measures read them with an `'__ALL__'` row filter (Step 2 and Step 6).

---

## 2. Model view — relationships and date table

Open the **Model** view (left rail, third icon).

### 2.1 Create dim → fact relationships (single direction)

For every relationship, drag the **dim** key onto the **fact** key. In the **Create relationship** dialog confirm: **Cardinality = One to many (1:\*)**, **Cross-filter direction = Single**, **Make this relationship active = checked**. Single direction only — never Both.

There are **19 relationships** in total. Rather than one long list, they're grouped by the layout tab you build them in (§2.4) — the **Core Sales** and **Profit** tabs share no fact table, so the split is clean and no relationship is ever created twice: **Core Sales** carries 9, **Profit** carries 10 (9 + 10 = 19), and **Data Quality** has none. Create each tab's relationships as you build that tab; the per-tab tables are in **§2.4**.

Notes:
- `mart_customer_summary` also has `preferred_site_sk` / `preferred_country_sk` — leave these **unrelated** (they are attributes, not the active grain). If Power BI auto-created inactive relationships on them, leave them inactive.
- `dim_site` also relates to `mart_customer_summary[preferred_site_sk]`? No — do not create it. Keep only the `customer_sk` relationship active.
- If Power BI auto-detected any relationship with **Both** cross-filter, edit it back to **Single**.

### 2.2 Mark the date table

1. Select `dim_date` in the Fields pane.
2. **Table tools → Mark as date table → Mark as a date table.**
3. Date column: **`date_day`**. Confirm the validation passes (contiguous, unique dates). Click **OK**.

This enables time-intelligence (MoM measures in Step 3 use `dim_date`).

### 2.3 Disconnected recon tables

`recon_cost_coverage` and `recon_payment_fee_coverage` stay **fully disconnected** from the star — no relationships. Each has one row per site plus a `'__ALL__'` roll-up row; the gating measures read the `'__ALL__'` row directly (`CALCULATE(..., recon_cost_coverage[site_sk] = "__ALL__")` style — see the measure library). `recon_csv_vs_dbt_revenue`, `recon_csv_vs_dbt_profit`, and `recon_woo_vs_csv_shipping_charged` are also disconnected and surfaced only via the Data Quality page (Step 5, Page 9), related by date only if the authored measures require it — otherwise leave disconnected and display their own columns directly.

### 2.4 Diagram layout for readability

With ~18 tables the Model View canvas gets messy fast. Relationships flow **one-to-many, dim → fact**, so lay it out as a star: **dimensions along the top, facts below, arrows pointing downward.** That reads like a waterfall instead of a spider web.

```
┌─ _Measures ─┐     ← park top-left, alone (no relationships)

  ── DIMENSIONS (top row) ─────────────────────────────────────
  dim_date   dim_site   dim_country   dim_customer_anonymized   dim_product   dim_payment_method
      │  ╲      │   ╲        │    ╲              │                    │              │
  ── FACTS (below, sharing the dims above) ────────────────────
  fact_order ── fact_order_item ── fact_refund
  mart_order_profit   mart_product_profit   mart_country_profit   mart_customer_summary
  fact_order_cost

  ── DISCONNECTED (bottom-right corner, fenced off) ───────────
  recon_cost_coverage  recon_payment_fee_coverage  recon_csv_vs_dbt_revenue
  recon_csv_vs_dbt_profit  recon_woo_vs_csv_shipping_charged
```

- Put **`dim_date` at one end** of the dimension row — it touches the most tables, so keeping it at the edge minimizes crossing lines.
- Keep **`fact_order` as the hub** in the fact row (it relates to date, site, country, customer, and payment method).
- **Fence the 5 `recon_*` views in a corner.** They are disconnected by design (§2.3) — physically separating them stops you hunting for a "missing" relationship.
- Keep **`_Measures` alone in the top-left** — no columns, no relationships.

**Biggest win — use multiple layout tabs.** Don't cram everything into one diagram. At the bottom of Model View, the **All tables** tab has a **`+`** to add layouts; drag a *subset* into each. Each tab below lists the tables to place **and the exact relationships to create there** — every one uses the §2.1 dialog settings (1:\*, single direction, active).

#### Tab 1 · All tables
Every table (the overview above). No relationships unique to this tab — it is the union of Core Sales + Profit, so nothing new is wired here.

#### Tab 2 · Core Sales
**Tables:** `dim_date`, `dim_site`, `dim_country`, `dim_product`, `dim_customer_anonymized`, `dim_payment_method` + `fact_order`, `fact_order_item`, `fact_refund`.

| From (dim, "one") | To (fact, "many") | Key |
|---|---|---|
| `dim_date` | `fact_order` | date_sk |
| `dim_date` | `fact_order_item` | date_sk |
| `dim_date` | `fact_refund` | date_sk |
| `dim_site` | `fact_order` | site_sk |
| `dim_site` | `fact_order_item` | site_sk |
| `dim_site` | `fact_refund` | site_sk |
| `dim_country` | `fact_order` | country_sk |
| `dim_product` | `fact_order_item` | product_sk |
| `dim_customer_anonymized` | `fact_order` | customer_sk |

*(`dim_payment_method` is placed but left unrelated — see the note in §2.1.)*

#### Tab 3 · Profit
**Tables:** the five dimensions above + `mart_order_profit`, `mart_product_profit`, `mart_country_profit`, `mart_customer_summary`, `fact_order_cost`.

| From (dim, "one") | To (mart/fact, "many") | Key |
|---|---|---|
| `dim_date` | `mart_order_profit` | date_sk |
| `dim_date` | `mart_product_profit` | date_sk |
| `dim_date` | `mart_country_profit` | date_sk |
| `dim_date` | `fact_order_cost` | date_sk |
| `dim_site` | `mart_order_profit` | site_sk |
| `dim_site` | `mart_product_profit` | site_sk |
| `dim_site` | `fact_order_cost` | site_sk |
| `dim_country` | `mart_country_profit` | country_sk |
| `dim_product` | `mart_product_profit` | product_sk |
| `dim_customer_anonymized` | `mart_customer_summary` | customer_sk |

#### Tab 4 · Data Quality
**Tables:** `recon_cost_coverage`, `recon_payment_fee_coverage`, `recon_csv_vs_dbt_revenue`, `recon_csv_vs_dbt_profit`, `recon_woo_vs_csv_shipping_charged` (+ `_Measures`).

**Relationships: none** — every table here is disconnected by design (§2.3).

Each tab shows only what you are reasoning about — far easier than one giant canvas.

**Micro-tips:** collapse fact cards (the `˄` on the header) and expand only when wiring relationships; hide key/`_sk` columns from report view (right-click → **Hide in report view**) so they clutter neither the diagram nor the field list; drag tables so every 1-to-many arrowhead points **down** and no line crosses another.

---

## 3. Create the `_Measures` table and paste the DAX

1. **Home → Enter data.** A blank table editor opens.
2. Name the table **`_Measures`** (the leading underscore sorts it to the top). Click **Load**.
3. In the Fields pane, expand `_Measures`. It has one dummy `Column1`. You will delete it after adding the first measure (a table must have at least one field until then).
4. Open `powerbi/measures/dax_measures.txt`. It contains one measure per block, each with its **name**, **DAX expression**, **format string**, and **Description** noted. For each measure:
   - Select the `_Measures` table → **Table tools → New measure**.
   - Paste the full `Name = <expression>` block into the formula bar; commit with Enter.
   - With the measure selected, set **Measure tools → Format → Custom** and paste the format string from the file's `// [Name] | format: …` annotation exactly as written (money `\$#,0.00`, counts `#,0`, fractions `0.0%`, pre-scaled coverage `0.00\%`). Do **not** substitute a plain `0.0%` on the coverage measures — they already return a 0–100 value, so `%` would multiply by 100 again and silently break tier gating. Text measures take no format.
   - Set the **Description** in **Model view**, not the ribbon: switch to Model view → click the measure in the Data pane → **Properties** pane (right side) → **Description**. (The Measure tools ribbon's Properties group only has Data category — there is no Description box there.) Paste the measure's comment text; these cross-link to `METRICS_DEFINITION.md`, so keep the section reference (e.g. "See METRICS_DEFINITION §B5").
5. After the first measure exists, select `_Measures[Column1]` → right-click → **Delete** (and delete the placeholder value). The table now holds only measures.

The measure library defines (grouped by use):

- **Sales (§A):** `[Revenue]`, `[Net Revenue]`, `[Orders]`, `[AOV]`, `[AIV]`, `[Quantity Sold]`, `[Shipping Charged to Customer]`, `[Shipping Charged Ratio]`, and their MoM variants (`[Revenue MoM %]`, `[Net Revenue MoM %]`, `[Shipping Charged MoM %]`, `[Contribution Profit MoM %]`).
- **Refunds (§C):** `[Refund Rate]`, `[Cancellation Rate]`, `[Refund Amount]`, `[Refund Revenue Share]`.
- **Profit (§B), tier-gated:** `[Contribution Profit]`, `[Profit Margin]`, `[ROI]`, plus the display-safe wrappers that return BLANK when profit is hidden.
- **Customers (§I):** `[Distinct Customers]`, `[Repeat Customer Share]`, `[Orders per Customer]`, `[Repeat Revenue Share]`.
- **Operations:** `[Open Backlog]` (`COUNT(fact_order WHERE status='processing')`).
- **Gating & disclosure (§J):** `[Cost Coverage %]`, `[Payment Fee Coverage %]`, `[Profit Visible Flag]`, `[Profit Unavailable Banner]`, `[Partial Coverage Chip]`, `[Payment Fee Chip]`, `[Profit Caveat Banner]`.

> If any measure errors on paste, the usual cause is a table/column name typo — every name must match the real schema in Step 1 exactly (e.g. `mart_order_profit[net_revenue_usd]`, `fact_order[shipping_charged_usd]`, `fact_order_item[line_revenue_usd]`, `fact_order_item[is_revenue_status]`). `revenue_usd` on `mart_order_profit` is an alias of `net_revenue_usd` — either works, but prefer whatever the authored measure uses.

---

## 4. Apply the theme

1. **View → Themes → Browse for themes.**
2. Select `powerbi/themes/ecommerce_theme.json` → **Open.**
3. Confirm the theme applied (accent colors, background, fonts change). The theme encodes the accessible palette and the tier colors (green/yellow/red) referenced by the chips. Site comparison should use shape/pattern in addition to color, per `DASHBOARD_SPEC §10`.

---

## 5. Build the pages

Rename Page 1 at the bottom tab. Build pages **1, 2, 3, 4, and 9** only (Pages 5–8 stay hidden this phase — right-click their tab → **Hide page** if any exist).

Global page furniture (add to every page):
- A **Slicer** on `dim_date[date_day]` (Between / relative "last 30 days" default per `DASHBOARD_SPEC §0`). Use **Sync slicers** (View → Sync slicers) so date filters follow across pages.
- A **Slicer** on `dim_site[site_name]` and one on `dim_country[country_name]`, synced as sticky page filters.
- A small **Data Quality strip** (two card visuals): `[Cost Coverage %]` and `[Payment Fee Coverage %]`, plus a card for `[Payment Fee Chip]` text.

### Page 1 — Executive Overview

Rename tab to **Executive Overview**.

**KPI cards (top row, `Card` visuals):**
- `[Revenue]` with `[Revenue MoM %]` (as a second card or as the callout's supporting value).
- `[Net Revenue]` with `[Net Revenue MoM %]`.
- `[Orders]`.
- `[AOV]`.
- `[Shipping Charged to Customer]` with `[Shipping Charged MoM %]`.
- `[Refund Rate]`.
- `[Cancellation Rate]`.
- `[Open Backlog]`.
- **Profit cards (tier-gated — see Step 6):** `[Contribution Profit]` with `[Contribution Profit MoM %]`, `[Profit Margin]`, `[ROI]`.

**Charts:**
1. **Line chart** — Axis `dim_date[date_day]` (last 90 days); Values `[Revenue]` and `[Contribution Profit]`. (Profit series is tier-gated.)
2. **Clustered bar** — Axis `dim_site[site_name]`; Values `[Revenue]` and `[Contribution Profit]`. Differentiate sites by pattern, not color alone.
3. **Horizontal bar** — Axis `dim_country[country_name]`; Value `[Revenue]`; Top-N filter = 10 by `[Revenue]`.
4. **Histogram / column** — order count bucketed by profit margin (profit-gated). Build via a margin-bucket grouping on `mart_order_profit[profit_margin]` (Power BI **New group** → bins) with count of `order_sk`.
5. **Card** — `[Open Backlog]` (already in KPI row; optional duplicate emphasis).

**Required banners on this page:**
- **Profit Caveat Banner** (a card/text box bound to `[Profit Caveat Banner]`) — must appear whenever any profit visual shows. Place it directly above or beside the profit cards. Text: "Customer shipping charge is counted as revenue. COGS is the all-in per-order fulfilment cost (already includes supplier fulfillment/shipping fee), so shipping is never subtracted as a cost. Revenue is net of refunds." (Approach A — see `docs/METRIC_CHANGES.md`.)
- **Profit Unavailable Banner** (`[Profit Unavailable Banner]`) — only renders when coverage < 80%. In the live GREEN state it returns BLANK and stays hidden.

### Page 2 — Product Performance

Rename tab to **Product Performance**.

**KPI cards:** distinct products sold (`COUNTROWS(DISTINCT dim_product[product_sk])` via `[Distinct Products Sold]` if provided, else a measure over `mart_product_profit`); avg units/order; best-selling product by units / revenue / `[Contribution Profit]` (profit variant shown only when profit visible).

**Charts:**
1. **Table + sparkline** — Rows `dim_product[product_name]`; Values `[Contribution Profit]` (or `[Revenue]` when profit unavailable), with an 8-week sparkline column. Top-20 filter.
2. **Scatter** — X `[Revenue]`, Y `[Profit Margin]` (fallback Y `[AOV]` when profit unavailable); details `dim_product[product_name]`.
3. **Donut** — Legend `dim_product[product_type]`; Value `[Revenue]`.
4. **Bar** — top 15 design topics (group over `dim_product` design/topic attribute); Value `[Revenue]`.
5. **Small multiples** — product launch date → cumulative revenue.

**Product-profit caveat chip:** on every product profit visual, add a card/text bound to the chip that renders when `mart_product_profit[cost_allocation_method] <> 'line_exact'` — text "Profit allocated by revenue share — not exact line-level cost" linking to `DATA_MODEL.md §4.3`. (Use a measure such as `[Product Cost Allocation Chip]` from the library, or a visual-level filter on `cost_allocation_method`.)

### Page 3 — Country / Market Performance

Rename tab to **Country / Market**.

**KPI cards:** top country by `[Revenue]`; top country by `[Profit Margin]` (when profit visible); country count.

**Charts:**
1. **Map** (filled or bubble) — Location `dim_country[country_name]`; bubble size `[Revenue]`; color `[Profit Margin]` (gray when profit unavailable).
2. **Sortable table** — Rows `dim_country[country_name]`; Values `[Orders]`, `[Revenue]`, `[AOV]`, `[Profit Margin]`, `[Refund Rate]`, `[Shipping Charged Ratio]`.
3. **Bar — Shipping Charged Ratio by country** — Axis `dim_country[country_name]`; Value `[Shipping Charged Ratio]` (= `SUM(shipping_charged_usd) / SUM(line_revenue_usd)`). **Title/label this "Shipping charged to customer / revenue (NOT shipping cost)".** See Step 7.
4. **Bar — refund rate by country** — Value `[Refund Rate]`; visual-level filter to hide countries with `[Orders]` < 10.

### Page 4 — Customer / Repeat Purchase

Rename tab to **Customer / Repeat**.

**KPI cards:** `[Distinct Customers]`; `[Repeat Customer Share]`; `[Orders per Customer]`; `[Repeat Revenue Share]`.

**Charts:**
1. **Cohort retention heatmap** — first-order month (`mart_customer_summary[first_order_date]` → month) × subsequent order months (via `fact_order` + `dim_date`). Use a matrix visual with conditional-formatted color scale.
2. **Stacked bar** — repeat vs new orders, monthly (split on `mart_customer_summary[is_repeat]`).
3. **Table** — customers per country (`dim_country[country_name]` via `preferred_country_sk` attribute or joined orders).

**Guest-checkout disclosure (required, see Step 7):** a text box on the page stating identity is reconstructed from hashed normalized billing email; one person/two emails = two customers, shared inbox = one customer, typos create duplicates; customer-level rows are private and the public portfolio uses synthetic data.

### Page 9 — Data Quality (sub-page)

Rename tab to **Data Quality**. Always-on operational view.

**Cards / gauges (from the disconnected recon tables, `'__ALL__'` row):**
- **Cost Coverage %** `[Cost Coverage %]` with tier indicator (red < 80 / yellow 80–95 / green ≥ 95). Live: **98.79% green**.
- **Cost Allocation Coverage %** and **COGS Coverage %** (from `recon_cost_coverage` columns `cost_coverage_pct` / `cogs_coverage_pct`).
- **Payment Fee Coverage %** `[Payment Fee Coverage %]` with source split (`recon_payment_fee_coverage` by `payment_fee_source`: `api_exact` / `plugin_parser` / `seed_estimate` / `missing`). Live: **98.03%** (revenue-order basis) — above target, so the payment-fee chip stays off. (`recon_payment_fee_coverage` also exposes `all_order_coverage_pct` = 79.50% as informational.)

**Drift tables/charts (disconnected recon tables):**
- CSV vs Woo revenue daily drift — `recon_csv_vs_dbt_revenue`.
- CSV vs dbt profit daily drift — `recon_csv_vs_dbt_profit`.
- Woo vs CSV shipping-charged daily drift — `recon_woo_vs_csv_shipping_charged`.

Phase 5/6 rows (fulfillment coverage, GA4 ratios/match) are omitted this phase.

---

## 6. Tier-gating mechanics (profit visibility)

Profit visibility is driven entirely by `[Cost Coverage %]` (revenue-order basis, read from the `'__ALL__'` row of `recon_cost_coverage`) and `[Payment Fee Coverage %]` (`'__ALL__'` row of `recon_payment_fee_coverage`). The authored measures encode the tiers from `METRICS_DEFINITION §J`.

### 6.1 Hiding profit visuals when coverage < 80%

Use `[Profit Visible Flag]` (returns 1 when `[Cost Coverage %] >= 80`, else 0). Two equivalent approaches — pick one and apply it consistently:

- **Visual-level filter (simplest):** on each profit visual (the profit cards, the profit line series, the margin histogram, the profit scatter, map color), add a **visual-level filter** on `[Profit Visible Flag]` with **is 1**. When coverage drops below 80%, the flag becomes 0 and the visual renders empty/blank.
- **Bookmark toggle:** build two bookmarks — "Profit shown" (profit visuals visible) and "Profit hidden" (profit visuals hidden, replaced by the unavailable banner). Because Power BI cannot auto-switch bookmarks from a measure, prefer the visual-level filter for automatic behavior; use bookmarks only for a manual reviewer override. If you use bookmarks, drive selection via the Selection pane show/hide state and document that it is a manual toggle.

The **display-safe measure wrappers** already return BLANK when `[Profit Visible Flag] = 0`, so cards bound to `[Contribution Profit]` etc. blank out automatically; the visual-level flag filter additionally removes chart series.

### 6.2 Surfacing the banners/chips as card visuals

Each of these is a **Card (text) visual** bound to a measure that returns the message string when its condition holds and BLANK otherwise (so the card self-hides when empty — enable "show blank as empty"):

| Card visual | Bound measure | Renders when | Live state |
|---|---|---|---|
| Profit Unavailable Banner | `[Profit Unavailable Banner]` | `[Cost Coverage %] < 80` | Hidden (coverage 98.79%) |
| Partial Coverage Chip | `[Partial Coverage Chip]` | `80 <= [Cost Coverage %] < 95` | Hidden (coverage ≥ 95%) |
| Payment Fee Chip | `[Payment Fee Chip]` | `[Payment Fee Coverage %] < 80` | **Hidden** (98.03%) |
| Profit Caveat Banner | `[Profit Caveat Banner]` | any profit visual shown (`[Profit Visible Flag] = 1`) | **Shown** |

Placement:
- **Profit Caveat Banner** goes on **Page 1 (Executive Overview)**, adjacent to the profit cards — it is mandatory whenever profit is shown. Optionally repeat a compact version on Page 2/Page 3 wherever profit visuals appear.
- **Payment Fee Chip** attaches next to each profit visual (or once per page in the Data Quality strip). In the live state it will be visible everywhere profit shows.
- **Partial Coverage Chip** and **Profit Unavailable Banner** are placed on Page 1 but stay hidden in the current GREEN state; they exist so the dashboard self-corrects if coverage later drops.

### 6.3 Expected live rendering

With coverage **98.79% (GREEN)** and payment-fee **98.03% (≥ 80%)**: all profit cards/charts **visible**, **no** partial-coverage chip, Profit Unavailable banner **hidden**, Profit Caveat Banner **visible**, Payment Fee Chip **hidden**. Verify this exact combination before saving.

---

## 7. Required disclosures / labeling

- **Customer page (Page 4) — guest-checkout disclosure (mandatory):** text box stating: "All sites use guest checkout. Customer identity is reconstructed from the hashed, normalized billing email. One person using two emails counts as two customers; a shared inbox counts as one; typos create duplicates. Customer-level rows are private — the public portfolio uses fully synthetic data." (Per `METRICS_DEFINITION §I` / `DASHBOARD_SPEC §4`.)
- **Country page (Page 3) — shipping labeling (mandatory):** the Shipping Charged Ratio bar and the ratio table column must be labeled **"shipping charged to customer / revenue (NOT shipping cost)"**. This is revenue-side; supplier shipping is inside `cogs_usd`. Never label it "shipping cost". There is no `actual_shipping_cost_usd` anywhere in the model.
- **Profit Caveat Banner** (Page 1) text is fixed above — it restates that customer shipping is revenue, COGS is the all-in fulfilment cost (already contains supplier shipping, so shipping is never a cost), and revenue is net of refunds.

---

## 8. Save, export, and capture

1. **File → Save as → `powerbi/ecommerce_analytics.pbix`** (overwrite the existing scaffold file at that path).
2. **Export the measures** back to `powerbi/measures/dax_measures.txt` so the text library stays the source of truth. Options:
   - Manually copy each measure's `Name = expression`, format, and Description into the file, **or**
   - Use Tabular Editor / DAX Studio (external tools) to script the `_Measures` table's measures out to text. Keep the same one-measure-per-block layout with format + Description.
3. **Capture screenshots** of each built page (Executive Overview, Product Performance, Country/Market, Customer/Repeat, Data Quality) to `powerbi/screenshots/` — PNG, at a consistent window size. These document the live GREEN-coverage / payment-fee-chip state for the portfolio.
4. Commit `powerbi/ecommerce_analytics.pbix`, `powerbi/measures/dax_measures.txt`, `powerbi/themes/ecommerce_theme.json`, `powerbi/screenshots/*`, and this guide.

---

## Verification checklist

- [ ] All 18 tables imported (Import mode); recon coverage tables disconnected from the star.
- [ ] All dim→fact relationships single-direction, active; `dim_date` marked as date table on `date_day`.
- [ ] `_Measures` table holds every measure from `dax_measures.txt` with correct format strings and Descriptions; dummy column deleted.
- [ ] Theme applied from `ecommerce_theme.json`.
- [ ] Pages 1–4 and 9 built per spec; Pages 5–8 hidden.
- [ ] Profit visuals gated by `[Profit Visible Flag]`; live state shows profit (98.79% GREEN).
- [ ] Payment Fee Chip **hidden** (98.03% ≥ 80%); Partial Coverage Chip and Profit Unavailable banner also hidden.
- [ ] Profit Caveat Banner visible on Page 1.
- [ ] Guest-checkout disclosure on Page 4; "shipping charged to customer / revenue (NOT cost)" labeling on Page 3.
- [ ] No reference anywhere to `actual_shipping_cost_usd`, and no `revenue_usd` column pulled from `fact_order` (revenue rolls up from `fact_order_item[line_revenue_usd]`).
- [ ] Saved to `powerbi/ecommerce_analytics.pbix`; measures exported; screenshots captured.
