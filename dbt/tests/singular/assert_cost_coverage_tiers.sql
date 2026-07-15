{{ config(severity='warn') }}

-- Tiered warning on cost coverage (METRICS_DEFINITION §J). Measured over
-- REVENUE-generating orders (is_revenue_status) — profit only applies to those,
-- and dead orders will never carry cost. Warns whenever revenue-order coverage
-- is below the fully-trusted green tier (>=95%): a returned row means the
-- dashboard is NOT green (<80% red / 80–95% yellow). Warn, not error — low
-- coverage is a data-completeness signal, not a pipeline failure.

with revenue_set as (
    select distinct order_sk
    from {{ ref('fact_order_item') }}
    where is_revenue_status
),

cov as (
    select
        count(distinct oc.order_sk) filter (where r.order_sk is not null)::numeric as covered_revenue_orders,
        (select count(*) from revenue_set)::numeric                                as revenue_orders
    from {{ ref('fact_order_cost') }} oc
    left join revenue_set r on r.order_sk = oc.order_sk
)

select
    covered_revenue_orders,
    revenue_orders,
    round(100.0 * covered_revenue_orders / nullif(revenue_orders, 0), 2) as cost_coverage_pct
from cov
where 100.0 * covered_revenue_orders / nullif(revenue_orders, 0) < 95
