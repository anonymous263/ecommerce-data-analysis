{{ config(materialized='view') }}

-- Order line items, typed. Revenue lives here (line_total_src -> USD in
-- fact_order_item). Variant attributes (Size/Color/Style/Fit Type/Print on the)
-- come from WCPA item meta_data display_key rows (WOO_PAYLOAD_AUDIT §4) because
-- all products are type=simple and variation_id is unused. Values are packed by
-- the plugin (e.g. 'L | L | #ffffff') so we keep the first pipe segment as the
-- clean attribute. Free-text personalization (Customize Text / Upload your
-- design) is PII and is deliberately NOT surfaced.
--
-- print_location additionally strips one-or-more trailing price-surcharge
-- suffixes (e.g. 'Back ($0.00)', 'Both side (£5.95) (£5.95)' — some raw values
-- repeat the surcharge group twice) that survive the pipe split because,
-- unlike Size/Color/Style/Fit Type, this field is not pipe-packed by WCPA —
-- the raw value already carries the human label + surcharge(s). Size/Color/
-- Style/Fit Type were sampled clean (no '(...)' pollution) and are left as-is.

with src as (
    select
        i.site_code,
        i.woo_order_id,
        i.woo_order_item_id,
        i._payload as p
    from {{ source('raw', 'woo_order_items') }} i
),

attrs as (
    select
        s.site_code,
        s.woo_order_id,
        s.woo_order_item_id,
        max(case when m->>'display_key' = 'Size'         then m->>'value' end) as size_raw,
        max(case when m->>'display_key' = 'Color'        then m->>'value' end) as color_raw,
        max(case when m->>'display_key' = 'Style'        then m->>'value' end) as style_raw,
        max(case when m->>'display_key' = 'Fit Type'     then m->>'value' end) as fit_type_raw,
        max(case when m->>'display_key' = 'Print on the' then m->>'value' end) as print_location_raw
    from src s
    left join lateral jsonb_array_elements(s.p->'meta_data') as m on true
    group by s.site_code, s.woo_order_id, s.woo_order_item_id
)

select
    s.site_code,
    s.woo_order_id,
    s.woo_order_item_id,
    (s.p->>'product_id')::bigint                                as woo_product_id,
    s.p->>'name'                                                as product_name_at_sale,
    s.p->>'sku'                                                 as sku,
    greatest(coalesce((s.p->>'quantity')::int, 0), 0)          as quantity,

    -- money in source currency (order currency; FX applied in fact_order_item)
    nullif(s.p->>'price', '')::numeric                         as unit_price_src,
    nullif(s.p->>'subtotal', '')::numeric                      as line_subtotal_src,
    nullif(s.p->>'total', '')::numeric                         as line_total_src,

    -- variant attributes: keep clean first segment of the WCPA-packed value
    nullif(trim(split_part(a.size_raw,           '|', 1)), '') as size,
    nullif(trim(split_part(a.color_raw,          '|', 1)), '') as color,
    nullif(trim(split_part(a.style_raw,          '|', 1)), '') as style,
    nullif(trim(split_part(a.fit_type_raw,       '|', 1)), '') as fit_type,
    nullif(
        trim(regexp_replace(
            split_part(a.print_location_raw, '|', 1),
            '(\s*\([^)]*\))+\s*$',
            ''
        )),
        ''
    ) as print_location
from src s
left join attrs a
    on  a.site_code         = s.site_code
    and a.woo_order_id      = s.woo_order_id
    and a.woo_order_item_id = s.woo_order_item_id
