{{ config(materialized='table') }}

-- Country × day profit roll-up (DATA_MODEL §7.3). Aggregates mart_order_profit
-- to (country_sk, date_sk); country comes from fact_order (billing country).
-- revenue_usd and contribution_profit_usd are read straight from
-- mart_order_profit, which defines revenue_usd as NET of refunds on the
-- product + customer-shipping base (Approach A) — this roll-up therefore
-- inherits net revenue/profit (shipping included) with no separate shipping or
-- refund logic needed here.

with profit as (
    select order_sk, date_sk, revenue_usd, cogs_usd, design_fee_usd,
           payment_fee_usd, contribution_profit_usd
    from {{ ref('mart_order_profit') }}
),

order_country as (
    select order_sk, country_sk from {{ ref('fact_order') }}
)

select
    {{ dbt_utils.generate_surrogate_key(['oc.country_sk', 'p.date_sk']) }} as country_profit_sk,
    oc.country_sk,
    p.date_sk,
    count(*)                                as order_count,
    round(sum(p.revenue_usd), 6)            as revenue_usd,
    round(sum(coalesce(p.cogs_usd, 0)), 6)          as cogs_usd,
    round(sum(coalesce(p.design_fee_usd, 0)), 6)    as design_fee_usd,
    round(sum(coalesce(p.payment_fee_usd, 0)), 6)   as payment_fee_usd,
    round(sum(p.contribution_profit_usd), 6)        as contribution_profit_usd
from profit p
inner join order_country oc on oc.order_sk = p.order_sk
group by oc.country_sk, p.date_sk
