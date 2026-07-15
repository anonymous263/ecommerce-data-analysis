{{ config(materialized='table') }}

-- Product-level (line-grain) profit with allocated cost (DATA_MODEL §4.3).
-- Grain: one order line item, restricted to orders that have cost enrichment
-- (INNER JOIN fact_order_cost).
--
-- COGS lives only at order level in the sheet, so it is allocated to lines by
-- revenue share:
--     line_cogs_usd = order.cogs_usd * (line.line_revenue_usd / order.revenue_usd)
-- Every row is tagged cost_allocation_method='allocated_by_revenue_share',
-- cost_confidence=0.60 so dashboards can show the allocation caveat.
--
-- NOTE (denominator scope): order_rev.order_revenue_usd sums ALL lines on the
-- order, not just is_revenue_status ones (line_revenue_usd is never zeroed for
-- non-revenue lines — see fact_order_item). line_cogs_usd therefore conserves
-- to the order's cogs_usd only when you sum it across every line of the order;
-- a consumer that first filters to is_revenue_status and THEN rolls up will
-- get a total less than mart_order_profit.cogs_usd. Documented, not "fixed" —
-- changing the denominator would make cogs_usd stop reconciling to the sheet
-- for orders with a mix of revenue and non-revenue lines.
--
-- Restricted (via the cost CTE) to orders present in mart_order_profit, i.e.
-- orders with is_revenue_status revenue > 0 — the same universe as order-level
-- profit, so a zero-revenue order's lines never get phantom allocated cost.

with items as (
    select
        order_item_sk,
        order_sk,
        site_sk,
        date_sk,
        product_sk,
        woo_line_item_id,
        woo_product_id,
        quantity,
        line_revenue_usd,
        is_revenue_status
    from {{ ref('fact_order_item') }}
),

order_rev as (
    -- denominator for revenue-share allocation: total line revenue per order
    select order_sk, sum(line_revenue_usd) as order_revenue_usd
    from {{ ref('fact_order_item') }}
    group by order_sk
),

cost as (
    -- sourced from mart_order_profit (not fact_order_cost directly) so this
    -- mart is restricted to the same revenue-bearing-order universe as
    -- order-level profit (MEDIUM-4: zero-revenue orders are excluded there).
    select order_sk, cogs_usd from {{ ref('mart_order_profit') }}
)

select
    i.order_item_sk,
    i.order_sk,
    i.site_sk,
    i.date_sk,
    i.product_sk,
    i.woo_line_item_id,
    i.woo_product_id,
    i.quantity,
    i.line_revenue_usd,

    case
        when orv.order_revenue_usd is not null and orv.order_revenue_usd <> 0
        then round(c.cogs_usd * (i.line_revenue_usd / orv.order_revenue_usd), 6)
    end                                     as line_cogs_usd,

    'allocated_by_revenue_share'            as cost_allocation_method,
    cast(0.60 as numeric)                   as cost_confidence,
    i.is_revenue_status
from items i
inner join cost c on c.order_sk = i.order_sk
left join order_rev orv on orv.order_sk = i.order_sk
