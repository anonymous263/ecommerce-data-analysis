{{ config(materialized='table') }}

-- Per-customer behavioral summary. Grain: one row per customer_hash. Revenue is
-- rolled up from fact_order_item (the single revenue source). total_profit_usd
-- is intentionally NULL: cost (COGS/design fee) does not exist until Phase 3's
-- fact_order_cost, so contribution profit cannot be computed yet.

with order_rev as (
    select order_sk, sum(line_revenue_usd) as order_revenue_usd
    from {{ ref('fact_order_item') }}
    group by order_sk
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
        coalesce(r.order_revenue_usd, 0) as order_revenue_usd
    from base b
    left join order_rev r on r.order_sk = b.order_sk
),

agg as (
    select
        customer_hash,
        count(distinct order_sk)                              as total_orders,
        round(sum(order_revenue_usd), 6)                      as total_revenue_usd,
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
    cast(null as numeric)                                             as total_profit_usd,
    (total_orders > 1)                                                as is_repeat,
    {{ dbt_utils.generate_surrogate_key(['preferred_site_code']) }}    as preferred_site_sk,
    {{ dbt_utils.generate_surrogate_key(['preferred_country_code']) }} as preferred_country_sk
from agg
