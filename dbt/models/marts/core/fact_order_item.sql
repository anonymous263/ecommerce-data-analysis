{{ config(materialized='table') }}

-- Line-item fact. INVARIANT: this is the ONE place revenue lives —
-- line_revenue_usd = line_total_src (net line total) FX-converted to USD.
-- Currency/date/order_sk come from the parent order (items carry no currency).
-- Sold variant attributes (size/color/style/fit/print_location) live here per
-- the dim_product grain decision (products are simple; attrs are order-time).
--
-- order_status / is_revenue_status: per WOO_PAYLOAD_AUDIT §5, only
-- completed/processing/refunded orders are revenue-bearing; failed/cancelled/
-- pending are not. line_revenue_usd itself is NOT zeroed out for non-revenue
-- orders (it stays the true line amount), so official revenue rollups MUST
-- filter `WHERE is_revenue_status` (see METRICS_DEFINITION.md §A).

with items as (
    select * from {{ ref('stg_woo_order_items') }}
),

orders as (
    select
        site_code,
        woo_order_id,
        currency_source,
        order_date,
        status
    from {{ ref('stg_woo_orders') }}
),

fx as (
    select distinct on (upper(currency))
        upper(currency) as currency,
        usd_rate
    from {{ ref('fx_rates') }}
    order by upper(currency), date desc
)

select
    {{ dbt_utils.generate_surrogate_key(['i.site_code', 'i.woo_order_id', 'i.woo_order_item_id']) }} as order_item_sk,
    {{ dbt_utils.generate_surrogate_key(['i.site_code', 'i.woo_order_id']) }}    as order_sk,
    {{ dbt_utils.generate_surrogate_key(['i.site_code']) }}                      as site_sk,
    to_char(o.order_date, 'YYYYMMDD')::int                                       as date_sk,
    {{ dbt_utils.generate_surrogate_key(['i.site_code', 'i.woo_product_id']) }}  as product_sk,

    i.woo_order_item_id           as woo_line_item_id,
    i.woo_product_id,
    i.quantity,
    i.unit_price_src,
    i.line_subtotal_src,
    i.line_total_src,
    coalesce(fx.usd_rate, 1.0)    as fx_rate_to_usd,
    round(i.line_total_src * coalesce(fx.usd_rate, 1.0), 6) as line_revenue_usd,

    o.status                                                as order_status,
    (o.status in ('completed', 'processing', 'refunded'))   as is_revenue_status,

    -- sold variant attributes (order-item-time; see dim_product grain decision)
    i.size,
    i.color,
    i.style,
    i.fit_type,
    i.print_location
from items i
left join orders o
    on o.site_code = i.site_code and o.woo_order_id = i.woo_order_id
left join fx
    on fx.currency = o.currency_source
