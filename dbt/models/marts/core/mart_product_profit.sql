{{ config(materialized='table') }}

-- Product-level (line-grain) profit with allocated cost (DATA_MODEL §4.3).
-- Grain: one order line item, restricted to orders present in mart_order_profit
-- (same revenue-bearing-order universe as order-level profit).
--
-- COGS (and now design_fee/payment_fee/refunds) live only at order level in
-- the sheet/Woo, so every one of these terms is allocated to lines by the SAME
-- revenue share:
--     line_<term>_usd = order.<term>_usd * (line.line_revenue_usd / order.revenue_usd)
-- Every row is tagged cost_allocation_method='allocated_by_revenue_share',
-- cost_confidence=0.60 so dashboards can show the allocation caveat.
--
-- NOTE (denominator scope): order_rev.order_revenue_usd sums ALL lines on the
-- order, not just is_revenue_status ones (line_revenue_usd is never zeroed for
-- non-revenue lines — see fact_order_item). This mart is restricted (via the
-- order_profit CTE, sourced from mart_order_profit) to orders where
-- gross_revenue_usd > 0, i.e. is_revenue_status = true — and is_revenue_status
-- is an ORDER-level property (derived from the single parent order status,
-- identical across every line of one order), so for every order in scope here
-- order_rev.order_revenue_usd (unfiltered) is numerically IDENTICAL to
-- mart_order_profit.gross_revenue_usd (filtered). That equality is what makes
-- every allocation below conserve EXACTLY: SUM(line_<term>_usd) over all lines
-- of an order equals the order's <term>_usd, and therefore
-- SUM(line_profit_usd) over all lines equals mart_order_profit.contribution_profit_usd.
--
-- cogs_usd/design_fee_usd/payment_fee_usd are coalesced to 0 before allocation
-- (matching mart_order_profit's own contribution_profit_usd treatment of nulls
-- as 0), so line-level conservation holds even for the handful of orders with
-- an unknown individual cost component.

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

order_profit as (
    -- sourced from mart_order_profit (not fact_order_cost/fact_refund directly)
    -- so this mart shares the exact order-level totals it must conserve to.
    -- effective_refund_usd (capped at gross, see mart_order_profit) is what's
    -- allocated — NOT the raw refunds_usd — so line net revenue floors at 0 and
    -- SUM(line_profit_usd) conserves to the capped order contribution_profit_usd.
    select
        order_sk, cogs_usd, design_fee_usd, payment_fee_usd,
        effective_refund_usd, contribution_profit_usd
    from {{ ref('mart_order_profit') }}
),

allocated as (
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
        i.is_revenue_status,
        case
            when orv.order_revenue_usd is not null and orv.order_revenue_usd <> 0
            then i.line_revenue_usd / orv.order_revenue_usd
        end                       as revenue_share,
        op.cogs_usd,
        op.design_fee_usd,
        op.payment_fee_usd,
        op.effective_refund_usd
    from items i
    inner join order_profit op on op.order_sk = i.order_sk
    left join order_rev orv on orv.order_sk = i.order_sk
)

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

    round(coalesce(effective_refund_usd, 0) * revenue_share, 6)                as line_refund_usd,
    round(line_revenue_usd - coalesce(effective_refund_usd, 0) * revenue_share, 6) as line_net_revenue_usd,
    round(coalesce(cogs_usd, 0)        * revenue_share, 6)            as line_cogs_usd,
    round(coalesce(design_fee_usd, 0)  * revenue_share, 6)            as line_design_fee_usd,
    round(coalesce(payment_fee_usd, 0) * revenue_share, 6)            as line_payment_fee_usd,
    round(
        (line_revenue_usd - coalesce(effective_refund_usd, 0) * revenue_share)
        - coalesce(cogs_usd, 0)        * revenue_share
        - coalesce(design_fee_usd, 0)  * revenue_share
        - coalesce(payment_fee_usd, 0) * revenue_share
    , 6)                                                              as line_profit_usd,

    'allocated_by_revenue_share'            as cost_allocation_method,
    cast(0.60 as numeric)                   as cost_confidence,
    is_revenue_status
from allocated
