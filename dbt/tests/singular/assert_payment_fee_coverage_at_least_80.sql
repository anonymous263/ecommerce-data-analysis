{{ config(severity='warn') }}

-- Warn when payment-fee coverage drops below 80% (METRICS_DEFINITION §J). Below
-- this threshold the dashboard shows an "estimated payment fee" chip. Warn, not
-- error — the plugin_parser source only covers ~79.5% of orders per the payload
-- audit, so this is an expected data-completeness signal.

with cov as (
    select
        count(payment_fee_usd)::numeric as orders_with_fee,
        count(*)::numeric               as woo_orders
    from {{ ref('fact_order') }}
)

select
    orders_with_fee,
    woo_orders,
    round(100.0 * orders_with_fee / nullif(woo_orders, 0), 2) as payment_fee_coverage_pct
from cov
where 100.0 * orders_with_fee / nullif(woo_orders, 0) < 80
