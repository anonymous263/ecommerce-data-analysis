{{ config(materialized='table') }}

-- Order-level contribution profit (DATA_MODEL §4.2). Grain: one Woo order that
-- has cost enrichment (INNER JOIN fact_order_cost).
--
-- contribution_profit_usd = revenue_usd − cogs_usd − design_fee_usd − payment_fee_usd
--   (LOCKED — no shipping subtraction; supplier shipping is already in cogs_usd)
--
-- revenue_usd = SUM(fact_order_item.line_revenue_usd) filtered by
-- is_revenue_status (only completed/processing/refunded are revenue-bearing —
-- matches every other revenue rollup, METRICS_DEFINITION §A). Only orders that
-- produced revenue are profit-bearing: an order whose lines are all
-- failed/cancelled/pending has no is_revenue_status revenue and is excluded
-- here (and therefore from mart_product_profit / mart_country_profit), so
-- profit and revenue are computed over the same universe rather than showing
-- phantom negative profit for orders that never actually sold anything.
--
-- payment_fee_usd: Woo (fact_order.payment_fee_usd) is primary; when Woo can't
-- provide an exact/estimated fee (payment_fee_usd IS NULL, ~20% of orders per
-- the payload audit), fall back to the CSV 'Fee' column (fact_order_cost.
-- payment_fee_fallback_usd, FX'd). payment_fee_source still reports Woo's own
-- classification ('missing' when the fallback was used) — recon_payment_fee_
-- coverage measures Woo exactness specifically, a separate signal from profit.

with cost as (
    select * from {{ ref('fact_order_cost') }}
),

order_hdr as (
    select order_sk, payment_fee_usd, payment_fee_source
    from {{ ref('fact_order') }}
),

revenue as (
    select
        order_sk,
        sum(line_revenue_usd) filter (where is_revenue_status) as revenue_usd
    from {{ ref('fact_order_item') }}
    group by order_sk
),

joined as (
    select
        c.order_sk,
        c.site_sk,
        c.date_sk,
        r.revenue_usd,
        c.cogs_usd,
        c.design_fee_usd,
        coalesce(h.payment_fee_usd, c.payment_fee_fallback_usd, 0) as payment_fee_usd,
        c.cost_confidence,
        c.cost_allocation_method,
        h.payment_fee_source
    from cost c
    inner join order_hdr h on h.order_sk = c.order_sk
    inner join revenue r on r.order_sk = c.order_sk and r.revenue_usd > 0
)

select
    order_sk,
    site_sk,
    date_sk,

    revenue_usd,
    cogs_usd,
    design_fee_usd,
    payment_fee_usd,

    round(
        revenue_usd
        - coalesce(cogs_usd, 0)
        - coalesce(design_fee_usd, 0)
        - coalesce(payment_fee_usd, 0)
    , 6)                            as contribution_profit_usd,

    round(
        (revenue_usd
         - coalesce(cogs_usd, 0)
         - coalesce(design_fee_usd, 0)
         - coalesce(payment_fee_usd, 0)) / revenue_usd
    , 6)                            as profit_margin,

    cost_confidence,
    cost_allocation_method,
    payment_fee_source
from joined
