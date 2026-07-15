{{ config(materialized='table') }}

-- Order-level cost enrichment fact (Phase 3). Grain: one Woo order.
-- Sourced from the manual sheet; joined to Woo orders by (site_code,
-- woo_order_id) so every row resolves to a real fact_order (INNER JOIN =>
-- order_sk relationships test holds, and non-FOS / unknown sheet rows drop).
--
-- FX: order-currency inputs (fee_src, csv_shipping_charged_src) are converted
-- to USD with the SAME date-aware fx_rates idiom as fact_order — keyed on the
-- CSV-trusted currency and the Woo order date (forward-filled seed, one row per
-- date/currency, no fan-out). cogs_usd/design_fee_usd are already USD.
--
-- INVARIANTS: there is no separate supplier-shipping cost field (that concept
-- does not exist in the data); csv_shipping_charged is the CUSTOMER charge, not
-- a cost; cogs_usd already includes the supplier fulfilment/shipping fee.

with cost as (
    select * from {{ ref('stg_manual_order_cost_enrichment') }}
),

orders as (
    select site_code, woo_order_id, order_date
    from {{ ref('stg_woo_orders') }}
),

fx as (
    select
        date               as rate_date,
        upper(currency)    as currency,
        usd_rate::numeric  as usd_rate
    from {{ ref('fx_rates') }}
)

select
    {{ dbt_utils.generate_surrogate_key(['c.site_code', 'c.woo_order_id']) }} as order_cost_sk,
    {{ dbt_utils.generate_surrogate_key(['c.site_code', 'c.woo_order_id']) }} as order_sk,
    {{ dbt_utils.generate_surrogate_key(['c.site_code']) }}                   as site_sk,
    to_char(o.order_date, 'YYYYMMDD')::int                                    as date_sk,

    c.cogs_usd,
    c.design_fee_usd,
    round(c.fee_src                  * coalesce(fx.usd_rate, 1.0), 6) as payment_fee_fallback_usd,
    round(c.csv_shipping_charged_src * coalesce(fx.usd_rate, 1.0), 6) as csv_shipping_charged_usd,

    -- recon-only observed values (NEVER official metrics)
    c.csv_revenue_observed_usd,
    c.csv_profit_observed_usd,

    c.cost_source,
    c.cost_allocation_method,
    c.cost_confidence
from cost c
inner join orders o
    on o.site_code = c.site_code and o.woo_order_id = c.woo_order_id
left join fx
    on fx.currency = upper(c.currency) and fx.rate_date = o.order_date
