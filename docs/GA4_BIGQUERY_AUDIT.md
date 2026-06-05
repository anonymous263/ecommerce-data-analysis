# GA4 BigQuery Audit — Phase 6 Deliverable

> **Placeholder doc.** This document is populated during Phase 6 by inspecting the live GA4 BigQuery export. Until then, every section is a question to answer, not a fact to copy.

## 0. Purpose

GA4 ecommerce is tracked via **GTM + PixelYourSite**, not the official WooCommerce GA4 plugin. Whether `transaction_id` reliably equals the Woo `order_id` is unknown until audited.

This audit determines:
1. Whether GA4 can be used for **funnel + landing page + behavior analytics**.
2. Whether GA4 can be used for **attribution and reconciliation against WooCommerce orders**.

The decision recorded at the end of this doc gates how the GA4 marts and Power BI pages are wired.

## 1. Audit Procedure

1. Confirm GA4 BigQuery export is enabled for every active site's GA4 property.
2. Connect with a read-only service account (`BigQuery Data Viewer` + `BigQuery Job User`).
3. Run the queries in sections 2–8 against the live `analytics_<property_id>` dataset(s).
4. Fill the tables below with real findings, one row per site.

## 2. Available BigQuery Tables

> `INFORMATION_SCHEMA.TABLES` query expected here.

| Site | Project | Dataset | Earliest `events_YYYYMMDD` | Latest `events_YYYYMMDD` | Intraday present? |
|---|---|---|---|---|---|
| (TBD) | | | | | |

## 3. Event Name Inventory (last 7 days)

| Site | event_name | event_count | first_seen | last_seen |
|---|---|---|---|---|
| (TBD) | | | | |

## 4. Ecommerce Event Coverage

| Site | view_item | add_to_cart | begin_checkout | add_shipping_info | add_payment_info | purchase | refund |
|---|---|---|---|---|---|---|---|
| (TBD) | | | | | | | |

## 5. Purchase Event Inspection

For each site, sample 20 `purchase` events and document:

| Field | Populated? | Sample value | Notes |
|---|---|---|---|
| `ecommerce.transaction_id` | (TBD) | | |
| `event_params[transaction_id]` | (TBD) | | |
| `ecommerce.purchase_revenue_in_usd` | (TBD) | | |
| `items[]` populated | (TBD) | | |
| `items[].item_id` | (TBD) | | |
| `items[].item_name` | (TBD) | | |
| `items[].price` | (TBD) | | |
| `items[].quantity` | (TBD) | | |

## 6. `transaction_id` Coverage

```sql
-- placeholder
SELECT
  COUNT(*) AS purchase_count,
  COUNTIF(ecommerce.transaction_id IS NOT NULL) AS with_transaction_id,
  SAFE_DIVIDE(COUNTIF(ecommerce.transaction_id IS NOT NULL), COUNT(*)) AS coverage_pct
FROM `<project>.analytics_<property_id>.events_*`
WHERE _TABLE_SUFFIX BETWEEN '20260501' AND '20260531'
  AND event_name = 'purchase';
```

| Site | purchase_count | with_transaction_id | coverage_pct |
|---|---|---|---|
| (TBD) | | | |

## 7. `transaction_id` Match Rate vs WooCommerce

Join GA4 `purchase` events to `fact_order.woo_order_id` per site:

| Site | ga4_purchase_count | matched_to_woo_order | match_rate_pct |
|---|---|---|---|
| (TBD) | | | |

## 8. Traffic Source Fields

For each site, confirm population of:

| Field | Populated? | Notes |
|---|---|---|
| `collected_traffic_source.manual_source` | (TBD) | session-scoped (preferred) |
| `collected_traffic_source.manual_medium` | (TBD) | |
| `collected_traffic_source.manual_campaign_name` | (TBD) | |
| `event_params[source]` | (TBD) | |
| `event_params[medium]` | (TBD) | |
| `event_params[campaign]` | (TBD) | |
| `traffic_source.source` | (TBD) | user first-touch |
| `traffic_source.medium` | (TBD) | |
| `traffic_source.name` | (TBD) | |

## 9. Device / Geo Fields

| Field | Populated? | Sample |
|---|---|---|
| `device.category` | (TBD) | desktop / mobile / tablet |
| `device.operating_system` | (TBD) | |
| `device.web_info.browser` | (TBD) | |
| `geo.country` | (TBD) | |
| `geo.region` | (TBD) | |
| `geo.city` | (TBD) | |

## 10. Decision Gate

Activation gate (per the strategy locked in [METRICS_DEFINITION.md §E15](METRICS_DEFINITION.md)):

- **`transaction_id` match rate ≥ 85%** → GA4 ↔ WooCommerce attribution **ACTIVE**. Reconciliation page enabled.
- **match rate < 85%** → GA4 is used for **funnel + landing page + behavior analytics only**. Attribution / reconciliation join suppressed in dbt.

**Decision (filled at end of audit):**

- [ ] Attribution active: yes / no
- [ ] Funnel + behavior analytics: yes / no
- [ ] Reasoning:

## 11. Summary & dbt staging implications

After filling in the sections above, write a short summary here:

- Sites with usable GA4 data: (TBD)
- Sessionization strategy: aggregate over `(user_pseudo_id, ga_session_id)`
- Items-array UNNEST strategy: (TBD)
- Traffic source field chosen: `collected_traffic_source.*` (session-scoped) preferred; fallback (TBD)
- Attribution join enabled/disabled per site: (TBD)
