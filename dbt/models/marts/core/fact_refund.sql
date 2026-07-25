{{ config(materialized='table') }}

-- Refund fact, ORDER-LEVEL grain (WOO_PAYLOAD_AUDIT §7: line_items empty on all
-- refunds, so order_item_sk is always NULL). refund_amount FX-converted using
-- the REAL daily ECB rate for the parent order's currency on the REFUND date
-- (not the order date — a refund can post on a different day than the order,
-- per DATA_MODEL §9 "book on refund date"). event_type derived from the
-- parent order status.

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
    -- one usd_rate per (date, currency); the seed is forward-filled daily so
    -- every refund date has an exact match for every supported currency
    select
        date               as rate_date,
        upper(currency)    as currency,
        usd_rate::numeric  as usd_rate
    from {{ ref('fx_rates') }}
),

order_keys as (
    -- conformed FKs inherited from the order header so refunds slice by
    -- country/customer/payment directly ([Refund Rate] by country etc.);
    -- one row per order_sk, no fan-out.
    select order_sk, country_sk, customer_sk, payment_method_sk
    from {{ ref('fact_order') }}
)

select
    {{ dbt_utils.generate_surrogate_key(['r.site_code', 'r.woo_refund_id']) }} as refund_sk,
    {{ dbt_utils.generate_surrogate_key(['r.site_code', 'r.woo_order_id']) }}  as order_sk,
    {{ dbt_utils.generate_surrogate_key(['r.site_code']) }}                    as site_sk,
    ok.country_sk,
    ok.customer_sk,
    ok.payment_method_sk,
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
   and fx.rate_date = r.refund_date
left join order_keys ok
    on ok.order_sk = {{ dbt_utils.generate_surrogate_key(['r.site_code', 'r.woo_order_id']) }}
