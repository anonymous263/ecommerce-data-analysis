{{ config(materialized='view') }}

-- Coupons, typed. Grain: one row per (site_code, woo_coupon_id).

with src as (
    select
        c.site_code,
        c.woo_coupon_id,
        c._payload as p,
        c.date_modified_gmt
    from {{ source('raw', 'woo_coupons') }} c
)

select
    site_code,
    woo_coupon_id,
    nullif(trim(p->>'code'), '')                  as coupon_code,
    p->>'discount_type'                           as discount_type,
    nullif(p->>'amount', '')::numeric             as amount,
    (p->>'date_created_gmt')::timestamptz         as created_at_utc,
    coalesce((p->>'date_modified_gmt')::timestamptz, date_modified_gmt) as modified_at_utc
from src
