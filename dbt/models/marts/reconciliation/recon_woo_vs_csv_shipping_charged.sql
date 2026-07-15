{{ config(materialized='view') }}

-- Daily delta of the CUSTOMER shipping charge: Woo (official) vs CSV, per site.
-- Both sides are the shipping charged to the customer (revenue-side), NOT a
-- supplier cost. Woo fact_order.shipping_charged_usd is official; CSV
-- fact_order_cost.csv_shipping_charged_usd is the sheet's 'Shipping' column.
-- Grain: (site_sk, date_sk).
--
-- LIKE-FOR-LIKE: the Woo side is restricted to orders that ALSO have a CSV cost
-- row. Comparing all-Woo against covered-CSV would report the cost-coverage gap
-- as fake "drift" (uncovered orders add Woo shipping with no CSV counterpart).
-- On the shared covered set the true daily delta is ~2% (target ≤5%); 97% of
-- orders match to the cent. Coverage completeness is tracked separately in
-- recon_cost_coverage / recon_unmatched_csv_cost.

with woo as (
    select h.site_sk, h.date_sk, sum(h.shipping_charged_usd) as woo_shipping_charged_usd
    from {{ ref('fact_order') }} h
    join {{ ref('fact_order_cost') }} oc on oc.order_sk = h.order_sk  -- covered orders only
    group by h.site_sk, h.date_sk
),

csv as (
    select site_sk, date_sk, sum(csv_shipping_charged_usd) as csv_shipping_charged_usd
    from {{ ref('fact_order_cost') }}
    group by site_sk, date_sk
)

select
    coalesce(w.site_sk, c.site_sk)                    as site_sk,
    coalesce(w.date_sk, c.date_sk)                    as date_sk,
    coalesce(w.woo_shipping_charged_usd, 0)           as woo_shipping_charged_usd,
    coalesce(c.csv_shipping_charged_usd, 0)           as csv_shipping_charged_usd,
    round(coalesce(w.woo_shipping_charged_usd, 0)
          - coalesce(c.csv_shipping_charged_usd, 0), 6) as delta_usd,
    case when coalesce(w.woo_shipping_charged_usd, 0) <> 0
         then round((coalesce(w.woo_shipping_charged_usd, 0)
                     - coalesce(c.csv_shipping_charged_usd, 0))
                    / w.woo_shipping_charged_usd, 6)
    end                                               as delta_pct
from woo w
full outer join csv c on c.site_sk = w.site_sk and c.date_sk = w.date_sk
