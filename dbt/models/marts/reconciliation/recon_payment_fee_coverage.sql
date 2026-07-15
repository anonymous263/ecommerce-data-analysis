{{ config(materialized='view') }}

-- Payment-fee coverage (METRICS_DEFINITION §J): overall % of Woo orders with a
-- non-null payment_fee_usd, plus a breakdown by payment_fee_source. The overall
-- figure is the '__ALL__' row (grouping sets). Payment-fee coverage <80% adds
-- an "estimated payment fee" chip on the dashboard.

with base as (
    select payment_fee_source, payment_fee_usd
    from {{ ref('fact_order') }}
)

select
    coalesce(payment_fee_source, '__ALL__')                     as payment_fee_source,
    count(*)                                                    as order_count,
    count(payment_fee_usd)                                      as orders_with_fee,
    round(100.0 * count(payment_fee_usd) / nullif(count(*), 0), 2) as fee_coverage_pct
from base
group by grouping sets ((payment_fee_source), ())
