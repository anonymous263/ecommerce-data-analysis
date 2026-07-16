{{ config(materialized='view') }}

-- Payment-fee coverage (METRICS_DEFINITION §H4 / §J). Like cost coverage (H1),
-- the GATING figure is measured over REVENUE-generating orders (an order with
-- >= 1 is_revenue_status line) — NOT all orders. Failed/cancelled/pending orders
-- never settled a payment, so no PayPal/Stripe gateway fee was ever charged and
-- their payment_fee_usd is (correctly) NULL; counting those as "uncovered"
-- understated coverage and falsely tripped the < 80% "estimated payment fee"
-- chip (all-orders 79.50% vs revenue-orders 98.03%). See docs/METRIC_CHANGES.md
-- (2026-07-16) — this mirrors the H1 cost-coverage rebasing in commit 727055c.
--
-- fee_coverage_pct (the gating metric) is the revenue-order basis;
-- all_order_coverage_pct (÷ every order) is kept as an informational column.
-- Grain: one row per payment_fee_source + a '__ALL__' overall row.

with revenue_set as (   -- one row per revenue-generating order (same rule as H1)
    select distinct order_sk
    from {{ ref('fact_order_item') }}
    where is_revenue_status
),

base as (
    select
        h.payment_fee_source,
        h.payment_fee_usd,
        (r.order_sk is not null) as is_revenue_order
    from {{ ref('fact_order') }} h
    left join revenue_set r on r.order_sk = h.order_sk
)

select
    coalesce(payment_fee_source, '__ALL__')                        as payment_fee_source,
    count(*)                                                        as order_count,
    count(payment_fee_usd)                                          as orders_with_fee,
    count(*) filter (where is_revenue_order)                        as revenue_orders,
    count(payment_fee_usd) filter (where is_revenue_order)          as revenue_orders_with_fee,
    round(100.0 * count(payment_fee_usd)
          / nullif(count(*), 0), 2)                                 as all_order_coverage_pct,  -- informational (÷ all orders)
    round(100.0 * count(payment_fee_usd) filter (where is_revenue_order)
          / nullif(count(*) filter (where is_revenue_order), 0), 2) as fee_coverage_pct  -- gating metric (÷ revenue orders)
from base
group by grouping sets ((payment_fee_source), ())
