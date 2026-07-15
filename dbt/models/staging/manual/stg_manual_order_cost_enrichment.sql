{{ config(materialized='view') }}

-- Manual cost enrichment, typed and cleaned. Grain: one Woo order.
-- No PII (dropped at load). Order-currency money stays *_src here; FX to USD
-- happens in fact_order_cost (same pattern as stg_woo_orders -> fact_order).
--
-- COGS/Design fee/Revenue/Profit are already USD in the sheet (parsed directly,
-- no FX). CoGS includes the supplier fulfilment/shipping fee — there is NO
-- separate supplier-shipping cost term anywhere (that concept does not exist).
-- CSV Shipping is the CUSTOMER shipping charge (csv_shipping_charged_*), kept
-- for reconciliation only, never a cost. CSV Revenue/Profit are recon-only.
--
-- cost_source/cost_allocation_method/cost_confidence describe the order-grain
-- cost: it is exact at order level ('order_only', confidence 1.00); product-
-- level allocation confidence is applied downstream in mart_product_profit.

with src as (
    select * from {{ source('raw', 'csv_order_management') }}
)

select
    site_code,
    woo_order_id,
    currency,
    order_date,

    -- already-USD cost inputs (direct, no FX)
    cogs_usd,
    design_fee_usd,

    -- order-currency money (FX->USD in fact_order_cost)
    fee_src,                          -- -> payment_fee_fallback_usd
    csv_shipping_charged_src,         -- customer shipping charge (recon only)

    -- recon-only observed values (already USD; NEVER official metrics)
    csv_revenue_observed_usd,
    csv_profit_observed_usd,

    'manual_csv'                    as cost_source,
    'order_only'                    as cost_allocation_method,
    cast(1.00 as numeric)           as cost_confidence
from src
