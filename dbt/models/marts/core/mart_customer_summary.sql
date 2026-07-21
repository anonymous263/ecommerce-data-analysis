{{ config(materialized='table') }}

-- Per-customer behavioral summary. Grain: one row per customer_hash. Revenue is
-- rolled up from fact_order_item (the single revenue source), NET of refunds.
-- total_profit_usd (Phase 3) sums contribution profit from mart_order_profit
-- over the customer's cost-covered orders; NULL when the customer has no
-- cost-enriched orders yet.

with order_rev as (
    -- filtered by is_revenue_status to match every other revenue rollup
    -- (fact_order_item, mart_order_profit) — an unfiltered sum here overstated
    -- per-customer revenue and was inconsistent with total_profit_usd below.
    select
        order_sk,
        sum(line_revenue_usd) filter (where is_revenue_status) as gross_revenue_usd
    from {{ ref('fact_order_item') }}
    group by order_sk
),

order_refunds as (
    -- refunds are a Woo-native concept independent of manual cost coverage, so
    -- they are pulled straight from fact_refund (not mart_order_profit) —
    -- total_revenue_usd nets refunds for EVERY order, not just cost-covered
    -- ones, keeping this summary's revenue coverage as broad as before.
    select order_sk, sum(refund_amount_usd) as refunds_usd
    from {{ ref('fact_refund') }}
    group by order_sk
),

order_ship as (
    -- customer shipping charge is revenue (Approach A) — pulled from fact_order
    -- (already FX'd to USD). Added only for revenue-bearing orders below so
    -- cancelled/failed orders don't contribute phantom shipping revenue.
    select order_sk, shipping_charged_usd
    from {{ ref('fact_order') }}
),

order_profit as (
    select order_sk, contribution_profit_usd
    from {{ ref('mart_order_profit') }}
),

base as (
    select
        o.customer_hash,
        o.site_code,
        coalesce(o.billing_country_code, 'XX')                               as country_code,
        o.order_date,
        {{ dbt_utils.generate_surrogate_key(['o.site_code', 'o.woo_order_id']) }} as order_sk
    from {{ ref('stg_woo_orders') }} o
),

joined as (
    select
        b.customer_hash,
        b.site_code,
        b.country_code,
        b.order_date,
        b.order_sk,
        -- revenue base = product line revenue + customer shipping (Approach A),
        -- net of refunds, floored at 0 per order. Shipping is added only when the
        -- order actually sold a product (gross_revenue_usd > 0), so cancelled/
        -- failed orders contribute no phantom shipping revenue. Woo refunds are
        -- full-order (incl. shipping); now that the base also includes shipping,
        -- the greatest(...,0) floor only guards the rare over-refund.
        greatest(
            coalesce(r.gross_revenue_usd, 0)
            + case when coalesce(r.gross_revenue_usd, 0) > 0
                   then coalesce(sh.shipping_charged_usd, 0) else 0 end
            - coalesce(rf.refunds_usd, 0)
        , 0) as order_revenue_usd,
        p.contribution_profit_usd        as order_profit_usd
    from base b
    left join order_rev r on r.order_sk = b.order_sk
    left join order_refunds rf on rf.order_sk = b.order_sk
    left join order_ship sh on sh.order_sk = b.order_sk
    left join order_profit p on p.order_sk = b.order_sk
),

agg as (
    select
        customer_hash,
        count(distinct order_sk)                              as total_orders,
        round(sum(order_revenue_usd), 6)                      as total_revenue_usd,
        round(sum(order_profit_usd), 6)                       as total_profit_usd,
        min(order_date)                                       as first_order_date,
        max(order_date)                                       as last_order_date,
        mode() within group (order by site_code)             as preferred_site_code,
        mode() within group (order by country_code)          as preferred_country_code
    from joined
    group by customer_hash
)

select
    {{ dbt_utils.generate_surrogate_key(['customer_hash']) }}          as customer_sk,
    customer_hash,
    first_order_date,
    last_order_date,
    total_orders,
    total_revenue_usd,
    total_profit_usd,
    (total_orders > 1)                                                as is_repeat,
    {{ dbt_utils.generate_surrogate_key(['preferred_site_code']) }}    as preferred_site_sk,
    {{ dbt_utils.generate_surrogate_key(['preferred_country_code']) }} as preferred_country_sk
from agg
