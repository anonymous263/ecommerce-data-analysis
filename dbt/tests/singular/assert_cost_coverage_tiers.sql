{{ config(severity='warn') }}

-- Tiered warning on cost coverage (METRICS_DEFINITION §J). Warns whenever
-- overall coverage is below the fully-trusted green tier (>=95%). A returned
-- row means the dashboard is NOT green: <80% = red (profit visuals hidden),
-- 80–95% = yellow (partial-coverage chip). Warn, not error — low coverage is a
-- data-completeness signal, not a pipeline failure.

with cov as (
    select
        count(distinct oc.order_sk)::numeric                      as covered_orders,
        (select count(*) from {{ ref('fact_order') }})::numeric   as woo_orders
    from {{ ref('fact_order_cost') }} oc
)

select
    covered_orders,
    woo_orders,
    round(100.0 * covered_orders / nullif(woo_orders, 0), 2) as cost_coverage_pct
from cov
where 100.0 * covered_orders / nullif(woo_orders, 0) < 95
