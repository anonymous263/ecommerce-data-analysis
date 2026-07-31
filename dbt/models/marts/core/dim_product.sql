{{ config(materialized='table') }}

-- =========================================================================
-- GRAIN DECISION (deliberate deviation from DATA_MODEL §5.3)
-- -------------------------------------------------------------------------
-- DATA_MODEL §5.3 lists size/color on dim_product. The Phase 1 payload audit
-- (WOO_PAYLOAD_AUDIT §4, §10) proves those are ORDER-ITEM-TIME attributes:
-- every product is type=simple (58,168/58,168), variation_id is unused, and
-- size/color/style/fit are synthesized per line via WCPA item meta. Putting
-- them on the product master would be wrong (one product sells in many
-- sizes/colors) and would explode the 58k-row master.
--
-- DECISION: dim_product is the CATALOG master at (site, woo_product_id) grain
-- (name/url/type/first_seen/last_seen). The sold variant attributes
-- (size/color/style/fit/print_location) live on fact_order_item instead. This
-- is the correct dimensional model; the reviewer should confirm this is the
-- intended resolution of the §5.3 vs audit conflict.
--
-- FK integrity: 7 order-item ROWS reference product_id=0 (deleted/placeholder,
-- absent from raw.woo_products), but they collapse to a SINGLE distinct
-- referenced-but-missing product_id (grouped by site_code, woo_product_id
-- below), so exactly 1 synthetic low-detail row is unioned in — not 7. Row
-- count is therefore 58,169 = 58,168 catalog rows + 1 synthetic row, and
-- fact_order_item.product_sk always resolves.
-- =========================================================================

with catalog as (
    select
        site_code,
        woo_product_id,
        product_name,
        product_url,
        product_type,
        sku,
        first_seen_at_utc::date as first_seen_date,
        last_seen_at_utc::date  as last_seen_date
    from {{ ref('stg_woo_products') }}
),

referenced as (
    -- product_ids sold but not present in the product master
    select
        i.site_code,
        i.woo_product_id,
        -- woo_product_id = 0 is Woo's placeholder for a DELETED product, so this
        -- one group can hold several unrelated designs (7 line items spanning 6
        -- designs as of the 2026-07 audit). max() would stamp all of them with
        -- whichever name happens to sort last, which reads on the dashboard as a
        -- real product that outsold its peers. Label the bucket for what it is.
        -- A real id merely absent from the master still keeps its sold name.
        case
            when i.woo_product_id = 0 then '(deleted product)'
            else max(i.product_name_at_sale)
        end                         as product_name,
        max(i.sku)                  as sku
    from {{ ref('stg_woo_order_items') }} i
    left join catalog c
        on c.site_code = i.site_code and c.woo_product_id = i.woo_product_id
    where c.woo_product_id is null
    group by i.site_code, i.woo_product_id
),

unioned as (
    select
        site_code, woo_product_id, product_name, product_url,
        product_type, sku, first_seen_date, last_seen_date
    from catalog

    union all

    select
        site_code,
        woo_product_id,
        coalesce(product_name, '(unknown product)') as product_name,
        null::text        as product_url,
        'unknown'         as product_type,
        sku,
        null::date        as first_seen_date,
        null::date        as last_seen_date
    from referenced
)

select
    {{ dbt_utils.generate_surrogate_key(['site_code', 'woo_product_id']) }} as product_sk,
    {{ dbt_utils.generate_surrogate_key(['site_code']) }}                   as site_sk,
    site_code,
    woo_product_id,
    product_name,
    product_url,
    product_type,
    sku,
    first_seen_date,
    last_seen_date
from unioned
