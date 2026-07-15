{{ config(materialized='view') }}

-- Cost coverage gate (METRICS_DEFINITION §J / DASHBOARD_SPEC §K): what share of
-- Woo orders have a fact_order_cost row (and a non-null cogs_usd). Drives the
-- dashboard tier: red <80% (hide profit), yellow 80–95% (partial chip),
-- green ≥95% (fully trusted). One row per site plus an overall '__ALL__' row.

with woo as (
    select site_sk, count(*) as woo_orders
    from {{ ref('fact_order') }}
    group by site_sk
),

covered as (
    select
        site_sk,
        count(distinct order_sk)                              as covered_orders,
        count(distinct order_sk) filter (where cogs_usd is not null) as cogs_orders
    from {{ ref('fact_order_cost') }}
    group by site_sk
),

per_site as (
    select
        w.site_sk::text                                       as site_sk,
        w.woo_orders,
        coalesce(c.covered_orders, 0)                         as covered_orders,
        coalesce(c.cogs_orders, 0)                            as cogs_orders
    from woo w
    left join covered c on c.site_sk = w.site_sk
),

overall as (
    select
        '__ALL__'                as site_sk,
        sum(woo_orders)          as woo_orders,
        sum(covered_orders)      as covered_orders,
        sum(cogs_orders)         as cogs_orders
    from per_site
),

unioned as (
    select * from per_site
    union all
    select * from overall
)

select
    site_sk,
    woo_orders,
    covered_orders,
    cogs_orders,
    round(100.0 * covered_orders / nullif(woo_orders, 0), 2) as cost_coverage_pct,
    round(100.0 * cogs_orders    / nullif(woo_orders, 0), 2) as cogs_coverage_pct,
    case
        when 100.0 * covered_orders / nullif(woo_orders, 0) >= 95 then 'green'
        when 100.0 * covered_orders / nullif(woo_orders, 0) >= 80 then 'yellow'
        else 'red'
    end                                                     as coverage_tier
from unioned
