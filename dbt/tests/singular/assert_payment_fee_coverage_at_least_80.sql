{{ config(severity='warn') }}

-- Warn when payment-fee coverage (REVENUE-order basis, METRICS_DEFINITION §H4 /
-- §J) drops below 80%. Below this the dashboard shows an "estimated payment fee"
-- chip. Measured over revenue orders (>= 1 is_revenue_status line) — dead
-- failed/cancelled/pending orders never charged a gateway fee, so they don't
-- count against coverage (see docs/METRIC_CHANGES.md, matches H1). On real FOS
-- data this is ~98% (GREEN); the warn fires only on a genuine capture gap.

with revenue_set as (
    select distinct order_sk
    from {{ ref('fact_order_item') }}
    where is_revenue_status
),

cov as (
    select
        count(h.payment_fee_usd)::numeric as orders_with_fee,
        count(*)::numeric                 as revenue_orders
    from {{ ref('fact_order') }} h
    join revenue_set r on r.order_sk = h.order_sk
)

select
    orders_with_fee,
    revenue_orders,
    round(100.0 * orders_with_fee / nullif(revenue_orders, 0), 2) as payment_fee_coverage_pct
from cov
where 100.0 * orders_with_fee / nullif(revenue_orders, 0) < 80
