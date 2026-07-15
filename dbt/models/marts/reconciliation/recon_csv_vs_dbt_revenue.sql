{{ config(materialized='view') }}

-- Drift monitor: CSV observed Revenue vs dbt official revenue, per order.
-- CSV Revenue is NEVER an official metric (DATA_MODEL §4.4) — this view exists
-- only to surface divergence. dbt revenue = SUM(fact_order_item.line_revenue_usd)
-- filtered by is_revenue_status (the single source of truth).

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
)

select
    c.order_sk,
    c.csv_revenue_observed_usd,
    coalesce(d.dbt_revenue_usd, 0)                                        as dbt_revenue_usd,
    round(c.csv_revenue_observed_usd - coalesce(d.dbt_revenue_usd, 0), 6) as delta_usd,
    case when coalesce(d.dbt_revenue_usd, 0) <> 0
         then round((c.csv_revenue_observed_usd - d.dbt_revenue_usd) / d.dbt_revenue_usd, 6)
    end                                                                   as delta_pct
from csv c
left join dbt_rev d on d.order_sk = c.order_sk
