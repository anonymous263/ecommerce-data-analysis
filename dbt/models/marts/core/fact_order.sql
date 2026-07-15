{{ config(materialized='table') }}

-- Order header fact. INVARIANT: NO revenue_usd column here (revenue lives once
-- on fact_order_item) — this prevents the order x item double-count.
-- shipping_charged_* is the CUSTOMER shipping charge (revenue-side), never a
-- cost. Money is FX-converted to USD via the fx_rates seed, which now carries
-- REAL daily ECB-backed rates (Frankfurter, forward-filled to every calendar
-- day) keyed by (date, currency) — the join below is DATE-AWARE (order date),
-- not "latest rate". The seed is forward-filled to every order date, so this
-- is a clean equality join with exactly one seed row per (date, currency) —
-- no fan-out. Payment fee is finalized here: plugin_parser (from order meta)
-- -> seed_estimate -> missing; the plugin fee FX also uses the order date
-- (the fee is charged same-day as the order) but keys off the processor's own
-- currency (_cs_*_currency), not the order currency.

with orders as (
    select * from {{ ref('stg_woo_orders') }}
),

fx as (
    -- one usd_rate per (date, currency); the seed is forward-filled daily so
    -- every order date has an exact match for every supported currency
    select
        date               as rate_date,
        upper(currency)    as currency,
        usd_rate::numeric  as usd_rate
    from {{ ref('fx_rates') }}
),

pay_seed as (
    -- active fallback rows only; the shipped seed is inactive, so this yields
    -- no matches and non-plugin orders fall through to 'missing' (audit §6)
    select
        payment_method,
        fee_percent,
        fixed_fee_usd
    from {{ ref('payment_fees') }}
    where is_active
),

joined as (
    select
        o.*,
        coalesce(fo.usd_rate, 1.0)   as fx_rate_to_usd,
        fp.usd_rate                  as fee_fx_rate,
        ps.fee_percent               as seed_fee_percent,
        ps.fixed_fee_usd             as seed_fixed_fee_usd
    from orders o
    left join fx fo
        on fo.currency = o.currency_source
       and fo.rate_date = o.order_date
    left join fx fp
        on fp.currency = o.plugin_payment_fee_currency
       and fp.rate_date = o.order_date
    left join pay_seed ps on ps.payment_method = o.payment_method
),

final as (
    select
        j.*,
        -- plugin fee converted from processor currency (fee_fx_rate)
        case when j.has_plugin_payment_fee
             then round(j.plugin_payment_fee_src * coalesce(j.fee_fx_rate, 1.0), 6)
        end as plugin_payment_fee_usd,
        -- seed estimate (only when an active seed row matched)
        case when not j.has_plugin_payment_fee and j.seed_fee_percent is not null
             then round(
                 coalesce(j.order_total_src, 0) * j.fx_rate_to_usd * j.seed_fee_percent
                 + coalesce(j.seed_fixed_fee_usd, 0), 6)
        end as seed_payment_fee_usd
    from joined j
)

select
    {{ dbt_utils.generate_surrogate_key(['site_code', 'woo_order_id']) }}   as order_sk,
    {{ dbt_utils.generate_surrogate_key(['site_code']) }}                   as site_sk,
    to_char(order_date, 'YYYYMMDD')::int                                    as date_sk,
    {{ dbt_utils.generate_surrogate_key(['customer_hash']) }}              as customer_sk,
    {{ dbt_utils.generate_surrogate_key(["coalesce(billing_country_code, 'XX')"]) }} as country_sk,
    {{ dbt_utils.generate_surrogate_key(["coalesce(nullif(trim(payment_method), ''), 'unknown')"]) }} as payment_method_sk,

    order_natural_key,
    woo_order_id,
    status,
    status_is_cancelled,
    currency_source,
    fx_rate_to_usd,

    order_total_src,
    round(order_total_src      * fx_rate_to_usd, 6) as order_total_usd,
    shipping_charged_src,
    round(shipping_charged_src * fx_rate_to_usd, 6) as shipping_charged_usd,
    discount_src,
    round(discount_src         * fx_rate_to_usd, 6) as discount_usd,
    tax_src,
    round(tax_src              * fx_rate_to_usd, 6) as tax_usd,

    coalesce(plugin_payment_fee_usd, seed_payment_fee_usd) as payment_fee_usd,
    case
        when has_plugin_payment_fee                     then 'plugin_parser'
        when seed_payment_fee_usd is not null           then 'seed_estimate'
        else 'missing'
    end as payment_fee_source,
    (not has_plugin_payment_fee and seed_payment_fee_usd is null) as payment_fee_needs_review,

    1 as order_count
from final
