# WooCommerce Payload Audit — Phase 1 Deliverable

> **Status: PENDING — requires a live pull after FOS key rotation.** Every field table below is **blocked** and intentionally left as `(TBD)`. Filling them requires the 20-order sample pull in §1, which cannot run until (a) the leaked FOS Woo consumer key is rotated and the new `WOO_FOS_KEY`/`WOO_FOS_SECRET` are in `.env`, and (b) the `ecommerce_postgres` container is up. No findings on this page are fabricated; each `(TBD)` marker means "awaiting live data". The extractor (`src/extract/woo_api.py`) that produces the sample is complete and tested.

> **Placeholder doc.** This document is populated during Phase 1 by inspecting real WooCommerce REST API responses. Until then, every section is a question to answer, not a fact to copy.

> **Scope note:** this doc covers **WooCommerce only** — Acowebs metadata, payment fee fields, custom statuses, refund grain, and currency fields. GA4-specific audit (transaction_id coverage, item array, traffic source fields) belongs in [GA4_BIGQUERY_AUDIT.md](GA4_BIGQUERY_AUDIT.md).

## 0. Purpose

The site uses two plugins that change the default WooCommerce REST payload:

- **WooCommerce Custom Product Addons by Acowebs** — likely surfaces POD variant data (size, type, color, addons) inside `line_items[].meta_data`. Exact keys unknown.
- A **payment gateway wrapper plugin** (not the official Stripe/PayPal plugin) — may or may not return the payment fee, and if so, in non-standard fields.

This audit must finish before Phase 2 staging models can finalize variant parsing and payment-fee handling.

## 1. Audit Procedure

For each active site in `config/sites.yaml`:

1. Pull the 20 most recent orders via `GET /wp-json/wc/v3/orders?orderby=date&order=desc&per_page=20`.
2. Save the JSON payload to `data/raw/audit/<site_code>/orders_sample.json` (gitignored).
3. For each order, also fetch `GET /wp-json/wc/v3/orders/<id>/refunds` and save under `refunds_sample.json`.
4. Fill in the sections below using real keys/values from the payloads.

## 2. Order-level fields (top-level keys)

> Fill with the union of keys observed across the 20-order sample per site.

| Key | Type | Example | Notes |
|---|---|---|---|
| (TBD) | | | |

## 3. `line_items[]` fields

| Key | Type | Example | Notes |
|---|---|---|---|
| (TBD) | | | |

## 4. `line_items[].meta_data` keys (Acowebs Custom Product Addons)

This is the highest-priority section. Document every meta_data key that appears for POD variants.

| `key` | `display_key` (if present) | `value` example | Used for |
|---|---|---|---|
| (TBD) | | | size / type / color / addon? |

**Parsing rules to confirm:**
- Can `product_type` (T-Shirt / Tank Top / Hoodie) be derived from `meta_data`, the `product` master, or only from the title?
- Can `gender_target` (M / W / Unisex) be derived automatically?
- Can `size` be parsed cleanly?
- Are addons captured here at all, or are they exposed only as a price modifier on the parent line?

## 5. Custom order statuses

WooCommerce default statuses: `pending`, `processing`, `on-hold`, `completed`, `cancelled`, `refunded`, `failed`.

| Status value seen | Standard? | Map to canonical status |
|---|---|---|
| (TBD) | | |

## 6. Payment fee fields

Document every field that **might** carry the payment processor fee. The wrapper plugin may expose it in any of:

- `meta_data` on the order (`_processing_fee`, `payment_fee_amount`, etc.)
- a dedicated `fee_lines[]` entry on the order
- nowhere (returned only by the gateway dashboard, not the WC API)

| Candidate location | Sample key | Sample value | Confidence |
|---|---|---|---|
| (TBD) | | | |

**Decision** (filled at end of audit, mapped to `payment_fee_source` enum in [METRICS_DEFINITION.md §B2](METRICS_DEFINITION.md)):

- [ ] Primary source for payment fee:
  - [ ] `api_exact` — direct field in API
  - [ ] `plugin_parser` — parsed from a plugin-specific location
  - [ ] `seed_estimate` — fall back to `dbt/seeds/payment_fees.csv`
  - [ ] `missing` — set `payment_fee_usd = NULL`, flag `payment_fee_needs_review = TRUE`
- [ ] Notes / parser path:

## 7. Refund fields

| `refunds[]` field (on order header) | Sample | Order-level or item-level? |
|---|---|---|
| (TBD) | | |

| `GET /orders/<id>/refunds` field | Sample | Order-level or item-level? |
|---|---|---|
| (TBD) | | |

**Decision** (filled at end of audit):

- [ ] Refund grain confirmed as **order-level by default**.
- [ ] Item-level refund support: enable? (default: no until evidence)

## 8. Currency fields

Per site, list which currencies appear in `currency` and whether `currency_code` is stable per order.

| Site | Currencies seen | Multi-currency in same site? |
|---|---|---|
| FOS | (TBD: USD/GBP/CAD/EUR expected) | yes |

## 9. Shipping charged to customer

The Woo order header includes a shipping total charged to the customer. Confirm which field carries it and how it interacts with the CSV `Shipping` column (which is also customer shipping charge — both are **shipping charged**, not supplier shipping cost; supplier fulfillment fee is inside COGS).

| Candidate Woo field | Sample value | Notes |
|---|---|---|
| `shipping_total` | (TBD) | likely primary |
| `shipping_tax` | (TBD) | tax on shipping |
| `shipping_lines[]` | (TBD) | per-line carrier? |

**Decision:**
- [ ] Official `shipping_charged_src` source: `<field name>`
- [ ] Define `recon_woo_vs_csv_shipping_charged` view to compare with CSV

## 10. Variant/Product master linkage

- Does each `line_items[i].product_id` resolve to a row in `/products`?
- Does each `line_items[i].variation_id` (when non-zero) resolve to a row in `/products/<id>/variations`?
- Or are POD variants synthesized at order time without a corresponding variation in the catalog?

## 11. Summary & dbt staging implications

After filling the sections above, write a short summary here:

- Variant parsing strategy chosen: (TBD)
- Payment fee parsing strategy chosen + `payment_fee_source` mapping: (TBD)
- Refund grain locked at: (TBD)
- Custom statuses to honor: (TBD)
- Shipping charged field chosen: (TBD)

The dbt models `stg_woo_order_items`, `stg_woo_orders`, and `stg_woo_refunds` are wired according to the decisions on this page.
