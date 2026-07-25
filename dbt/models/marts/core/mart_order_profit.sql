{{ config(materialized='table') }}

-- Order-level contribution profit (DATA_MODEL §4.2). Grain: one Woo order that
-- has cost enrichment (INNER JOIN fact_order_cost).
--
-- contribution_profit_usd = net_revenue_usd − cogs_usd − design_fee_usd − payment_fee_usd
--   where net_revenue_usd = gross_revenue_usd − effective_refund_usd
--   and   gross_revenue_usd = gross_product_revenue_usd + shipping_charged_usd
--   and   effective_refund_usd = LEAST(refunds_usd, gross_revenue_usd)
--
-- SHIPPING IS REVENUE (Approach A, 2026-07-21). The customer shipping charge
-- (fact_order.shipping_charged_usd) is money the store actually received, so it
-- belongs in the revenue base — NOT parked as recon-only. COGS (CSV column U) is
-- the ALL-IN per-order fulfilment cost (it already contains whatever the supplier
-- charged for shipping); the store both charged the customer for shipping AND
-- paid the supplier to fulfil, so both sides must appear. The old formula
-- subtracted the shipping-inclusive COGS while excluding the shipping the
-- customer paid — an asymmetry that understated profit by exactly the shipping
-- charged (~$40k across FOS). See docs/METRIC_CHANGES.md (2026-07-21) and
-- CLAUDE.md domain rules #1/#2/#4.
--
-- Refund netting is CAPPED at gross revenue. Woo refunds (fact_refund) are
-- FULL-ORDER refunds — they reimburse product + shipping (+ tax). Now that the
-- revenue base ALSO includes shipping, refund and revenue are on the same basis
-- (order total), so the cap almost never binds; it remains only as a floor-at-0
-- guard for the rare order refunded for more than it grossed. A fully-refunded
-- order nets revenue to exactly 0 (the sale is reversed, not inverted) and then
-- shows a COGS loss — correct, because the item WAS produced/fulfilled before
-- the money was returned (unlike failed/cancelled orders, which never incurred
-- COGS and are excluded upstream). refunds_usd is still exposed as the TRUE
-- amount returned (for refund metrics); effective_refund_usd is the portion
-- applied to the revenue base.
--
-- gross_product_revenue_usd = SUM(fact_order_item.line_revenue_usd) filtered by
-- is_revenue_status (only completed/processing/refunded are revenue-bearing —
-- matches every other revenue rollup, METRICS_DEFINITION §A). Only orders that
-- produced GROSS PRODUCT revenue are profit-bearing: an order whose lines are all
-- failed/cancelled/pending has no is_revenue_status revenue and is excluded here
-- (so its shipping is never counted as phantom revenue either), keeping profit
-- and revenue over the same universe. The zero-revenue exclusion is on GROSS
-- PRODUCT (pre-refund), not net — a fully refunded order still counts as "sold
-- something" and stays in scope with net_revenue reduced to (near) zero.
--
-- refunds_usd: fact_refund is order-level (refund_amount_usd is POSITIVE);
-- summed per order_sk. revenue_usd is kept as an ALIAS of net_revenue_usd so any
-- downstream consumer that reads "revenue_usd" gets the net (product + shipping,
-- less refund) figure.
--
-- payment_fee_usd: Woo (fact_order.payment_fee_usd) is primary; when Woo can't
-- provide an exact/estimated fee (payment_fee_usd IS NULL, ~20% of orders per
-- the payload audit), fall back to the CSV 'Fee' column (fact_order_cost.
-- payment_fee_fallback_usd, FX'd). payment_fee_source still reports Woo's own
-- classification ('missing' when the fallback was used).

with cost as (
    select * from {{ ref('fact_order_cost') }}
),

order_hdr as (
    -- conformed FKs (country/customer/payment) + degenerate status inherited from
    -- the order header so profit slices by them directly (no mart_country_profit,
    -- no TREATAS); one row per order_sk, so no fan-out.
    select
        order_sk, shipping_charged_usd, payment_fee_usd, payment_fee_source,
        country_sk, customer_sk, payment_method_sk, status as order_status
    from {{ ref('fact_order') }}
),

revenue as (
    select
        order_sk,
        sum(line_revenue_usd) filter (where is_revenue_status) as gross_product_revenue_usd
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
        r.gross_product_revenue_usd,
        coalesce(h.shipping_charged_usd, 0)            as shipping_charged_usd,
        r.gross_product_revenue_usd
            + coalesce(h.shipping_charged_usd, 0)      as gross_revenue_usd,
        coalesce(rf.refunds_usd, 0)                    as refunds_usd,
        least(
            coalesce(rf.refunds_usd, 0),
            r.gross_product_revenue_usd + coalesce(h.shipping_charged_usd, 0)
        )                                              as effective_refund_usd,
        r.gross_product_revenue_usd + coalesce(h.shipping_charged_usd, 0)
            - least(
                coalesce(rf.refunds_usd, 0),
                r.gross_product_revenue_usd + coalesce(h.shipping_charged_usd, 0)
            )                                          as net_revenue_usd,
        c.cogs_usd,
        c.design_fee_usd,
        coalesce(h.payment_fee_usd, c.payment_fee_fallback_usd, 0) as payment_fee_usd,
        c.cost_confidence,
        c.cost_allocation_method,
        h.payment_fee_source,
        h.country_sk,
        h.customer_sk,
        h.payment_method_sk,
        h.order_status
    from cost c
    inner join order_hdr h on h.order_sk = c.order_sk
    inner join revenue r on r.order_sk = c.order_sk and r.gross_product_revenue_usd > 0
    left join refunds rf on rf.order_sk = c.order_sk
)

select
    order_sk,
    site_sk,
    date_sk,

    round(gross_product_revenue_usd, 6) as gross_product_revenue_usd, -- product line revenue only (is_revenue_status)
    round(shipping_charged_usd, 6)      as shipping_charged_usd,       -- customer shipping charge (revenue-side)
    round(gross_revenue_usd, 6)         as gross_revenue_usd,          -- product + shipping (order-total basis)
    round(refunds_usd, 6)               as refunds_usd,                -- TRUE amount returned (product + shipping)
    round(effective_refund_usd, 6)      as effective_refund_usd,       -- portion applied to revenue base (capped at gross)
    round(net_revenue_usd, 6)           as net_revenue_usd,            -- gross − effective_refund (floored at 0)
    round(net_revenue_usd, 6)           as revenue_usd,  -- alias: downstream readers of "revenue_usd" get NET
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
    payment_fee_source,

    -- conformed FKs pushed to order grain (redesign 2026-07-24)
    country_sk,
    customer_sk,
    payment_method_sk,
    order_status
from joined
