{{ config(materialized='view') }}

-- Visibility for cost rows silently dropped by fact_order_cost's INNER JOIN.
-- Non-FOS sheet rows (other projects present in the same Google Sheet) are
-- correctly excluded there, but a FOS sheet row whose Order Code matches no
-- Woo order (typo, deleted order, or not-yet-ingested) also drops out with no
-- signal — this view surfaces exactly those rows so they can be investigated
-- and fixed at the source. Scoped to site_code = 'FOS' (the only ingested
-- WooCommerce site today, per config/sites.yaml); revisit if a second site
-- goes active.

with cost as (
    select * from {{ ref('stg_manual_order_cost_enrichment') }}
    where site_code = 'FOS'
),

woo_orders as (
    select site_code, woo_order_id from {{ ref('stg_woo_orders') }}
)

select
    c.site_code,
    c.woo_order_id                as order_code,
    c.order_date,
    c.currency,
    c.cogs_usd,
    c.design_fee_usd,
    c.csv_revenue_observed_usd
from cost c
left join woo_orders w
    on w.site_code = c.site_code and w.woo_order_id = c.woo_order_id
where w.woo_order_id is null
