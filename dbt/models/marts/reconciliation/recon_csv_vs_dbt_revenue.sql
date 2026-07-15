{{ config(materialized='view') }}

-- Drift monitor: CSV observed Revenue vs dbt official revenue, per order.
-- CSV Revenue is NEVER an official metric (DATA_MODEL §4.4) — this view exists
-- only to surface divergence. dbt revenue = SUM(fact_order_item.line_revenue_usd)
-- filtered by is_revenue_status (the single source of truth).
--
-- DEFINITIONAL NOTE: the sheet's Revenue is a GROSS order value ≈ line revenue
-- + customer shipping, whereas dbt revenue is NET line revenue (shipping lives
-- separately in fact_order.shipping_charged_usd). So `delta_usd` (vs net) is
-- large by construction (~shipping); the meaningful reconciliation is
-- `delta_vs_gross_usd` (vs dbt_revenue + shipping), which is small. Both are
-- exposed so the divergence is interpretable rather than alarming.

with csv as (
    select order_sk, csv_revenue_observed_usd
    from {{ ref('fact_order_cost') }}
),

dbt_rev as (
    select
        order_sk,
        sum(line_revenue_usd) filter (where is_revenue_status) as dbt_revenue_usd
    from {{ ref('fact_order_item') }}
    group by order_sk
),

ship as (
    select order_sk, shipping_charged_usd
    from {{ ref('fact_order') }}
)

select
    c.order_sk,
    c.csv_revenue_observed_usd,
    coalesce(d.dbt_revenue_usd, 0)                                        as dbt_revenue_usd,
    coalesce(s.shipping_charged_usd, 0)                                  as shipping_charged_usd,
    round(coalesce(d.dbt_revenue_usd, 0)
          + coalesce(s.shipping_charged_usd, 0), 6)                       as dbt_gross_usd,
    -- vs NET line revenue (large by construction — differs by ~shipping)
    round(c.csv_revenue_observed_usd - coalesce(d.dbt_revenue_usd, 0), 6) as delta_usd,
    case when coalesce(d.dbt_revenue_usd, 0) <> 0
         then round((c.csv_revenue_observed_usd - d.dbt_revenue_usd) / d.dbt_revenue_usd, 6)
    end                                                                   as delta_pct,
    -- vs GROSS (net + shipping) — the meaningful, near-zero reconciliation
    round(c.csv_revenue_observed_usd
          - (coalesce(d.dbt_revenue_usd, 0) + coalesce(s.shipping_charged_usd, 0)), 6) as delta_vs_gross_usd
from csv c
left join dbt_rev d on d.order_sk = c.order_sk
left join ship s on s.order_sk = c.order_sk
