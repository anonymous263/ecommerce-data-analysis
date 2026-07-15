{{ config(materialized='view') }}

-- Refunds, typed. Order-level grain (WOO_PAYLOAD_AUDIT §7): line_items is empty
-- on all refunds, so item-level allocation is not modeled. `amount` is the
-- refund total (source currency; FX to USD in fact_refund). event_type is
-- derived from the parent order status in fact_refund.

with src as (
    select
        r.site_code,
        r.woo_refund_id,
        r.woo_order_id,
        r._payload as p,
        r.date_created_gmt
    from {{ source('raw', 'woo_refunds') }} r
)

select
    site_code,
    woo_refund_id,
    woo_order_id,
    -- Woo stores refund amount as a negative-signed string on some stores; here
    -- it is positive. Take absolute value so refund_amount_src is magnitude.
    abs(nullif(p->>'amount', '')::numeric)        as refund_amount_src,
    nullif(trim(p->>'reason'), '')                as refund_reason,
    date_created_gmt                              as refund_created_at_utc,
    date_created_gmt::date                        as refund_date
from src
