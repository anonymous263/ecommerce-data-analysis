{{ config(materialized='table') }}

-- Refund fact, ORDER-LEVEL grain (WOO_PAYLOAD_AUDIT §7: line_items empty on all
-- refunds, so order_item_sk is always NULL). refund_amount FX-converted via the
-- parent order currency. event_type derived from the parent order status.

with refunds as (
    select * from {{ ref('stg_woo_refunds') }}
),

orders as (
    select
        site_code,
        woo_order_id,
        currency_source,
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
    {{ dbt_utils.generate_surrogate_key(['r.site_code', 'r.woo_refund_id']) }} as refund_sk,
    {{ dbt_utils.generate_surrogate_key(['r.site_code', 'r.woo_order_id']) }}  as order_sk,
    {{ dbt_utils.generate_surrogate_key(['r.site_code']) }}                    as site_sk,
    cast(null as text)                                                         as order_item_sk,
    to_char(r.refund_date, 'YYYYMMDD')::int                                    as date_sk,
    r.woo_refund_id,

    round(r.refund_amount_src * coalesce(fx.usd_rate, 1.0), 6)                as refund_amount_usd,
    r.refund_reason,
    case
        when o.status in ('cancelled', 'failed') then 'cancellation'
        else 'refund'
    end as event_type
from refunds r
left join orders o
    on o.site_code = r.site_code and o.woo_order_id = r.woo_order_id
left join fx
    on fx.currency = o.currency_source
