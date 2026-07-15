{{ config(materialized='view') }}

-- Product master, typed. Grain: one row per (site_code, woo_product_id) from
-- raw.woo_products. All products are type=simple; POD variant attributes are
-- NOT catalog variations (they are synthesized at order time via WCPA item
-- meta) so they live on fact_order_item, not here (see dim_product for the
-- grain decision).

with src as (
    select
        pr.site_code,
        pr.woo_product_id,
        pr._payload as p,
        pr.date_modified_gmt
    from {{ source('raw', 'woo_products') }} pr
)

select
    site_code,
    woo_product_id,
    p->>'name'                                          as product_name,
    p->>'permalink'                                     as product_url,
    p->>'type'                                          as product_type,
    p->>'sku'                                           as sku,
    p->>'status'                                        as product_status,
    (p->>'date_created_gmt')::timestamptz               as first_seen_at_utc,
    coalesce((p->>'date_modified_gmt')::timestamptz, date_modified_gmt) as last_seen_at_utc
from src
