{{ config(materialized='view') }}

-- Cost coverage gate (METRICS_DEFINITION §J / DASHBOARD_SPEC §K). Profit is only
-- defined for REVENUE-generating orders (is_revenue_status), so the tier that
-- gates the dashboard is measured over revenue orders — NOT all orders. Dead
-- failed/cancelled/pending orders will never carry cost and must not drag the
-- tier down. `all_order_coverage_pct` is kept as an informational column.
--
-- "Covered" requires a REAL cogs_usd value (> 0), not merely a fact_order_cost
-- ROW existing — a manual-sheet row with cogs_usd 0/null means "cost unknown",
-- not "cost captured"; counting it as covered would silently inflate profit
-- visibility for orders whose cost is actually missing. cost_coverage_pct
-- (the gating metric) and cogs_coverage_pct are the SAME percentage under this
-- rule; cogs_coverage_pct is kept as its own named column for dashboard/metric-
-- doc clarity (METRICS_DEFINITION §J references it explicitly).
--
-- Tier from revenue-order coverage: red <80% (hide profit), yellow 80–95%
-- (partial chip), green ≥95% (fully trusted). One row per site + '__ALL__'.

with all_orders as (
    select site_sk, count(*) as woo_orders
    from {{ ref('fact_order') }}
    group by site_sk
),

revenue_set as (   -- one row per revenue-generating order
    select distinct order_sk
    from {{ ref('fact_order_item') }}
    where is_revenue_status
),

rev_orders as (
    select h.site_sk, count(distinct h.order_sk) as revenue_orders
    from {{ ref('fact_order') }} h
    join revenue_set r on r.order_sk = h.order_sk
    group by h.site_sk
),

covered as (
    select
        h.site_sk,
        count(distinct oc.order_sk)                                                          as covered_orders,
        count(distinct oc.order_sk) filter (where r.order_sk is not null)                     as covered_revenue_orders,
        count(distinct oc.order_sk) filter (where r.order_sk is not null and oc.cogs_usd > 0) as covered_revenue_orders_with_cogs
    from {{ ref('fact_order_cost') }} oc
    join {{ ref('fact_order') }} h on h.order_sk = oc.order_sk
    left join revenue_set r on r.order_sk = oc.order_sk
    group by h.site_sk
),

per_site as (
    select
        a.site_sk::text                                 as site_sk,
        a.woo_orders,
        coalesce(rv.revenue_orders, 0)                   as revenue_orders,
        coalesce(c.covered_orders, 0)                     as covered_orders,
        coalesce(c.covered_revenue_orders, 0)             as covered_revenue_orders,
        coalesce(c.covered_revenue_orders_with_cogs, 0)   as covered_revenue_orders_with_cogs
    from all_orders a
    left join rev_orders rv on rv.site_sk = a.site_sk
    left join covered c on c.site_sk = a.site_sk
),

overall as (
    select
        '__ALL__'                                     as site_sk,
        sum(woo_orders)                                as woo_orders,
        sum(revenue_orders)                            as revenue_orders,
        sum(covered_orders)                            as covered_orders,
        sum(covered_revenue_orders)                    as covered_revenue_orders,
        sum(covered_revenue_orders_with_cogs)          as covered_revenue_orders_with_cogs
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
    revenue_orders,
    covered_orders,
    covered_revenue_orders,
    covered_revenue_orders_with_cogs,
    round(100.0 * covered_orders / nullif(woo_orders, 0), 2)                       as all_order_coverage_pct,
    round(100.0 * covered_revenue_orders_with_cogs / nullif(revenue_orders, 0), 2) as cost_coverage_pct,  -- gating metric
    round(100.0 * covered_revenue_orders_with_cogs / nullif(revenue_orders, 0), 2) as cogs_coverage_pct,  -- same basis, named for METRICS_DEFINITION §J
    case
        when 100.0 * covered_revenue_orders_with_cogs / nullif(revenue_orders, 0) >= 95 then 'green'
        when 100.0 * covered_revenue_orders_with_cogs / nullif(revenue_orders, 0) >= 80 then 'yellow'
        else 'red'
    end                                                                           as coverage_tier
from unioned
