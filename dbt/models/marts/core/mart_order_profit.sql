{{ config(materialized='table') }}

-- Order-level contribution profit (DATA_MODEL §4.2). Grain: one Woo order that
-- has cost enrichment (INNER JOIN fact_order_cost).
--
-- contribution_profit_usd = net_revenue_usd − cogs_usd − design_fee_usd − payment_fee_usd
--   where net_revenue_usd = gross_revenue_usd − effective_refund_usd
--   and   effective_refund_usd = LEAST(refunds_usd, gross_revenue_usd)
--   (LOCKED — no shipping subtraction; supplier shipping is already in cogs_usd)
--
-- Refund netting is CAPPED at gross revenue. Woo refunds (fact_refund) are
-- FULL-ORDER refunds — they reimburse product + shipping (+ tax), and confirmed
-- against the data every refunded order's refund equals the whole order total.
-- But the profit revenue base is line revenue only (shipping lives separately in
-- fact_order.shipping_charged_usd, never in this base — same reason the CSV
-- shipping recon is like-for-like). Subtracting a shipping-inclusive refund from
-- a shipping-excluding revenue would push product revenue negative (~$345 of
-- over-netting across 31 orders). So effective_refund_usd = LEAST(refunds,
-- gross): a full refund nets product revenue to exactly 0 (the sale is reversed,
-- not inverted), and a fully-refunded order then shows a COGS loss — correct,
-- because the item WAS produced/fulfilled before the money was returned (unlike
-- failed/cancelled orders, which never incurred COGS and are excluded upstream).
-- refunds_usd is still exposed as the TRUE amount returned (for refund metrics);
-- effective_refund_usd is the portion applied to product revenue.
--
-- gross_revenue_usd = SUM(fact_order_item.line_revenue_usd) filtered by
-- is_revenue_status (only completed/processing/refunded are revenue-bearing —
-- matches every other revenue rollup, METRICS_DEFINITION §A). Only orders that
-- produced GROSS revenue are profit-bearing: an order whose lines are all
-- failed/cancelled/pending has no is_revenue_status revenue and is excluded
-- here (and therefore from mart_product_profit / mart_country_profit), so
-- profit and revenue are computed over the same universe rather than showing
-- phantom negative profit for orders that never actually sold anything. The
-- zero-revenue exclusion is on GROSS (pre-refund), not net — a fully refunded
-- order still counts as "sold something" and stays in scope with net_revenue
-- reduced to (near) zero, rather than being silently dropped.
--
-- refunds_usd: fact_refund is order-level (refund_amount_usd is POSITIVE);
-- summed per order_sk. Netting refunds out of revenue matters because
-- is_revenue_status treats 'refunded' orders as revenue-bearing (they DID
-- sell), so without this a refunded order would show full gross revenue and
-- full positive profit despite the money having been returned. revenue_usd is
-- kept as an ALIAS of net_revenue_usd so any existing/downstream consumer that
-- reads "revenue_usd" gets the net figure, not gross.
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
        sum(line_revenue_usd) filter (where is_revenue_status) as gross_revenue_usd
    from {{ ref('fact_order_item') }}
    group by order_sk
),

refunds as (
    select order_sk, sum(refund_amount_usd) as refunds_usd
    from {{ ref('fact_refund') }}
    group by order_sk
),

joined as (
    select
        c.order_sk,
        c.site_sk,
        c.date_sk,
        r.gross_revenue_usd,
        coalesce(rf.refunds_usd, 0)                    as refunds_usd,
        least(coalesce(rf.refunds_usd, 0), r.gross_revenue_usd) as effective_refund_usd,
        r.gross_revenue_usd
            - least(coalesce(rf.refunds_usd, 0), r.gross_revenue_usd) as net_revenue_usd,
        c.cogs_usd,
        c.design_fee_usd,
        coalesce(h.payment_fee_usd, c.payment_fee_fallback_usd, 0) as payment_fee_usd,
        c.cost_confidence,
        c.cost_allocation_method,
        h.payment_fee_source
    from cost c
    inner join order_hdr h on h.order_sk = c.order_sk
    inner join revenue r on r.order_sk = c.order_sk and r.gross_revenue_usd > 0
    left join refunds rf on rf.order_sk = c.order_sk
)

select
    order_sk,
    site_sk,
    date_sk,

    round(gross_revenue_usd, 6)    as gross_revenue_usd,
    round(refunds_usd, 6)          as refunds_usd,             -- TRUE amount returned (incl. shipping)
    round(effective_refund_usd, 6) as effective_refund_usd,   -- portion applied to product revenue (capped at gross)
    round(net_revenue_usd, 6)      as net_revenue_usd,         -- gross − effective_refund (floored at 0)
    round(net_revenue_usd, 6)      as revenue_usd,  -- alias: downstream readers of "revenue_usd" get NET
    cogs_usd,
    design_fee_usd,
    payment_fee_usd,

    round(
        net_revenue_usd
        - coalesce(cogs_usd, 0)
        - coalesce(design_fee_usd, 0)
        - coalesce(payment_fee_usd, 0)
    , 6)                            as contribution_profit_usd,

    round(
        (net_revenue_usd
         - coalesce(cogs_usd, 0)
         - coalesce(design_fee_usd, 0)
         - coalesce(payment_fee_usd, 0)) / nullif(net_revenue_usd, 0)
    , 6)                            as profit_margin,  -- NULL when fully refunded (net_revenue_usd = 0)

    cost_confidence,
    cost_allocation_method,
    payment_fee_source
from joined
