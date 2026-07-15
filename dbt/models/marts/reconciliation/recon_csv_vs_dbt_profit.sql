{{ config(materialized='view') }}

-- Drift monitor: CSV observed Profit vs dbt contribution profit, per order.
-- CSV Profit is NEVER an official metric — informational only (DATA_MODEL §12).
-- dbt profit = mart_order_profit.contribution_profit_usd, which is now NET of
-- refunds; the CSV's own Profit figure uses whatever basis the sheet owner
-- used (not necessarily refund-aware), so some of the drift this view surfaces
-- for refunded orders is expected and not a dbt bug.

with csv as (
    select order_sk, csv_profit_observed_usd
    from {{ ref('fact_order_cost') }}
),

dbt_profit as (
    select order_sk, contribution_profit_usd
    from {{ ref('mart_order_profit') }}
)

select
    c.order_sk,
    c.csv_profit_observed_usd,
    p.contribution_profit_usd                                       as dbt_profit_usd,
    round(c.csv_profit_observed_usd - p.contribution_profit_usd, 6) as delta_usd,
    case when p.contribution_profit_usd <> 0
         then round((c.csv_profit_observed_usd - p.contribution_profit_usd) / p.contribution_profit_usd, 6)
    end                                                             as delta_pct
from csv c
inner join dbt_profit p on p.order_sk = c.order_sk
