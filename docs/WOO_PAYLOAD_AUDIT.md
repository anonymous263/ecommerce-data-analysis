# WooCommerce Payload Audit — Phase 1 Deliverable

> **Status: COMPLETE (2026-07-15).** Audited against the **full FOS backfill** landed in `raw.woo_*` — 4,757 orders, 5,190 line items, 34 refunds, 58,168 products, 79 coupons (stronger basis than the originally-planned 20-order sample). All figures below are structural/aggregate only — **no customer PII values** were extracted, only field names, plugin meta **keys**, and enum-like distributions (status/currency/payment method). Introspection queries ran over `_payload` JSONB via `jsonb_object_keys` / `jsonb_array_elements(...)->>'key'`.

> **Scope note:** WooCommerce only — Acowebs/WCPA metadata, payment-fee fields, statuses, refund grain, currency, shipping. GA4-specific audit (transaction_id match rate, item array, traffic source) belongs in [GA4_BIGQUERY_AUDIT.md](GA4_BIGQUERY_AUDIT.md).

## 0. Purpose & plugin landscape (confirmed)

The store's REST payload is shaped by several plugins:

- **WCPA — WooCommerce Custom Product Addons by Acowebs.** Surfaces all POD variant/personalization data inside `line_items[].meta_data` (raw blob key `_WCPA_order_meta_data`, plus human-labelled `display_key` entries). **All products are `type = simple` (58,168 / 58,168; zero `variable`)** — native Woo variations are *not* used; every variant attribute comes from WCPA item meta.
- **"mecom" payment wrappers** (`mecom_stripe`, `mecom_paypal`) + PayPal Commerce (`ppcp-gateway`). The processor fee is exposed in order `meta_data` (`_cs_stripe_fee` / `_cs_paypal_fee`), **not** in `fee_lines`.
- **WooCommerce Order Tracking** (`_wot_tracking_*`) — tracking id/carrier/status in order meta (Phase 5; must be hashed before staging).
- **WooCommerce native Order Attribution** (`_wc_order_attribution_*`) — utm/source/device (useful for Phase 6 GA4 cross-check).
- A **tip plugin** — populates `fee_lines[]` with `Tip (...)` entries (revenue-side, customer tips — **not** processing fees).

## 1. Audit basis

Ran structural introspection over the full `raw.woo_*` tables (post-backfill) rather than a 20-order file sample. Scripts (throwaway, not committed) queried key sets, meta-key frequencies, and enum distributions. No `data/raw/audit/*.json` dump was needed; raw JSONB is the source.

## 2. Order-level fields (top-level keys — union across 4,757 orders)

| Key | Notes |
|---|---|
| `id`, `number`, `order_key`, `status`, `version`, `created_via` | identifiers / provenance |
| `currency`, `currency_symbol`, `prices_include_tax` | **multi-currency** (see §8) |
| `date_created_gmt`, `date_modified_gmt`, `date_paid_gmt`, `date_completed_gmt` | **use GMT fields** (watermark = `date_modified_gmt`) |
| `total`, `total_tax`, `discount_total`, `discount_tax`, `cart_tax`, `shipping_total`, `shipping_tax` | money (strings; cast in staging) |
| `line_items[]`, `fee_lines[]`, `shipping_lines[]`, `tax_lines[]`, `coupon_lines[]`, `refunds[]` | nested arrays |
| `payment_method`, `payment_method_title`, `transaction_id`, `date_paid_gmt` | payment (see §6) |
| `shipping_total`, `shipping_lines[]` | customer shipping charge (see §9) |
| `meta_data[]` | plugin data (fees, tracking, attribution — see §6) |
| **PII (drop/hash in staging):** `billing`, `shipping`, `customer_note`, `customer_ip_address`, `customer_user_agent`, `customer_id` | never cross raw→staging unhashed |

## 3. `line_items[]` fields (union across 5,190 items)

| Key | Notes |
|---|---|
| `id`, `product_id`, `variation_id` | `variation_id` effectively unused (all products `simple`) |
| `name`, `parent_name`, `sku`, `global_unique_id`, `image` | product identity |
| `quantity`, `price`, `subtotal`, `subtotal_tax`, `total`, `total_tax` | line economics (revenue lives here → `fact_order_item`) |
| `tax_class`, `taxes` | tax detail |
| `meta_data[]` | **variant/personalization data (WCPA) — see §4** |

## 4. `line_items[].meta_data` keys (WCPA / Acowebs) — **highest priority**

Frequency across 5,190 line items (`key` == `display_key` for all attribute rows):

| `key` / `display_key` | Count | Used for |
|---|---|---|
| `_WCPA_order_meta_data` | 5,190 (100%) | **raw WCPA blob** (machine copy of all addons) |
| `Size` | 5,105 (98%) | **size** attribute |
| `Color` | 4,916 (95%) | **color** attribute |
| `Fit Type` | 4,861 (94%) | fit (e.g. men's/women's/unisex cut → proxy for gender) |
| `Print on the` | 4,859 (94%) | print location (front/back) |
| `Style` | 4,852 (93%) | **apparel style** (tee/tank/hoodie proxy) |
| `Color Type` | 120 | secondary color option |
| `Customize Text`, `Upload your design`, `Only ship to:`, `Print on:`, `Package` | ≤80 total | **personalization free-text/uploads → treat as PII, hash/drop; do not use as attributes** |

**Parsing decisions:**
- `size` → parse from `display_key = 'Size'`. Clean, 98% coverage. ✅ parseable.
- `color` → `display_key = 'Color'`. 95%. ✅
- `apparel style / product_type` (tee/tank/hoodie) → best source is `display_key = 'Style'` (93%) and/or product `name`/`categories`; **`product.type` is always `simple` and useless for this.** Parse `Style`, fall back to name/category heuristic in staging.
- `gender_target` → **not a discrete field.** Closest proxy is `Fit Type`. Derive best-effort in staging from `Fit Type` + product name/category; mark low-confidence.
- Free-text addons (`Customize Text`, `Upload your design`) contain **customer input → PII**; hash or drop, never expose as a dimension attribute.

## 5. Custom order statuses

Distribution across 4,757 orders — **all are standard WooCommerce core statuses; no custom statuses in use.**

| Status | Count | Standard? |
|---|---|---|
| `completed` | 3,699 | yes |
| `cancelled` | 497 | yes |
| `failed` | 437 | yes |
| `processing` | 90 | yes |
| `refunded` | 26 | yes |
| `pending` | 8 | yes |

**Decision:** no status remapping needed; staging maps 1:1 to canonical. Revenue recognition should count `completed`/`processing`/`refunded` per metrics spec; `failed`/`cancelled`/`pending` are non-revenue.

## 6. Payment fee fields — **found in order `meta_data`**

`fee_lines[]` = **customer tips** (662 orders; names all `Tip (...)`), **NOT** processing fees. The processor fee lives in order `meta_data`:

| Location | Key(s) | Orders | Notes |
|---|---|---|---|
| order `meta_data` (Stripe) | `_cs_stripe_fee`, `_cs_stripe_payout`, `_cs_stripe_currency` | 1,876 | fee in processor currency |
| order `meta_data` (PayPal) | `_cs_paypal_fee`, `_cs_paypal_payout`, `_cs_paypal_currency` | 1,906 | fee in processor currency |
| `fee_lines[]` | `Tip (...)` | 662 | **tips, not fees** — exclude from payment fee |

**Coverage:** 1,876 + 1,906 = **3,782 / 4,757 = 79.5%** of orders carry an exact plugin fee. Just below the 80% gate → per [DASHBOARD_SPEC §K], profit shows with an **"estimated payment fee"** chip until coverage ≥80%.

**Decision → `payment_fee_source`:**
- `plugin_parser` — parse `_cs_stripe_fee` / `_cs_paypal_fee` from order `meta_data` (primary; 79.5%).
- `seed_estimate` — fall back to `dbt/seeds/payment_fees.csv` for the ~20.5% without a plugin fee (mostly `ppcp-gateway`, `failed`/`cancelled`).
- `missing` — set `payment_fee_usd = NULL` where neither applies.
- **FX note:** the fee is in `_cs_*_currency` (processor currency), so staging must FX-convert the fee to USD, not assume order currency.

## 7. Refund fields & grain

`refunds[]` on the order header carries a summary (`{id, reason, total}`); full objects come from `GET /orders/<id>/refunds`.

Refund object keys (34 refunds): `id`, `amount`, `reason`, `date_created_gmt`, `refunded_by`, `refunded_payment`, `line_items`, `fee_lines`, `tax_lines`, `shipping_lines`, `meta_data`.

**`line_items` is empty on all 34 refunds → item-level refund allocation is not populated.**

**Decision:**
- ✅ Refund grain confirmed **order-level** (`stg_woo_refunds` keyed by `woo_refund_id`, `order_item_sk` nullable). Use `amount` as the refund total.
- ❌ Item-level refund support **not enabled** (no evidence in data).
- **Extractor optimization confirmed:** only 34/4,757 orders have a non-empty `refunds` summary, so `woo_api.py` skips the per-order `/refunds` GET when the summary is empty.

## 8. Currency fields

Single currency per order; four across the site (matches `config/sites.yaml` `supported_currencies`).

| Site | Currencies (order counts) | Multi-currency? |
|---|---|---|
| FOS | USD 2,229 · EUR 1,221 · GBP 1,209 · CAD 98 | **yes** — per-order `currency`; base is GBP but most sales are USD |

**Implication:** staging must FX-convert **every** money field to USD per the order's `currency` via `fx_rates` seed. Payment fee uses its own `_cs_*_currency` (§6).

## 9. Shipping charged to customer

| Field | Evidence | Notes |
|---|---|---|
| `shipping_total` | non-zero on 4,755 / 4,757 | **primary** customer shipping charge |
| `shipping_tax` | present | tax on shipping |
| `shipping_lines[]` | present on all 4,757 | per-method carrier detail |

**Decision:** `shipping_charged_src = shipping_total` → `fact_order.shipping_charged_usd` (FX-converted). This is the official customer shipping charge; `recon_woo_vs_csv_shipping_charged` compares it to the CSV `Shipping` column (also customer-side). Neither is supplier cost — supplier fulfillment fee stays inside COGS. **No `actual_shipping_cost_usd` field.**

## 10. Variant / product-master linkage

- `line_items[].product_id` resolves to `raw.woo_products` (all `simple`).
- `line_items[].variation_id` is present but unused (no `variable` products) — **do not** attempt `/products/<id>/variations`.
- POD variants are **synthesized at order time via WCPA addons** (§4), not catalog variations. `dim_product` is built from `raw.woo_products`; variant attributes (size/color/style/fit) come from the **order item meta**, not the product master.

## 11. Summary & dbt staging implications

- **Variant parsing:** from `line_items[].meta_data` `display_key` → `Size`, `Color`, `Style` (product_type proxy), `Fit Type` (gender proxy), `Print on the`. Ignore `variation_id`. Free-text personalization (`Customize Text`, `Upload your design`) = PII → hash/drop.
- **Payment fee:** `plugin_parser` from order meta `_cs_stripe_fee` / `_cs_paypal_fee` (79.5% coverage → "estimated payment fee" chip until ≥80%); `seed_estimate` fallback; FX from `_cs_*_currency`. `payment_fee_source ∈ {plugin_parser, seed_estimate, missing}` (no `api_exact` — no native field).
- **Refund grain:** order-level (`amount`); item-level disabled.
- **Custom statuses:** none — 1:1 canonical mapping.
- **Shipping charged:** `shipping_total` → `shipping_charged_usd` (FX). Recon vs CSV `Shipping`.
- **Currency/FX:** per-order `currency` (USD/EUR/GBP/CAD) → convert all money to USD via `fx_rates`.
- **Tracking (Phase 5):** `_wot_tracking_*` order meta → hash tracking ids before staging.
- **Attribution (Phase 6):** `_wc_order_attribution_*` + top-level `transaction_id` support GA4↔Woo matching.
- **Data hygiene:** some `fee_lines` names show mojibake for currency symbols (`£` → `�`); staging should not rely on `fee_lines` text (tips are out of scope for cost anyway).

`stg_woo_orders`, `stg_woo_order_items`, and `stg_woo_refunds` are to be wired per the decisions above.
