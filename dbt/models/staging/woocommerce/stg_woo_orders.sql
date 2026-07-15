{{ config(materialized='view') }}

-- Order header, typed and cleaned. PII (billing email) is hashed here via the
-- hash_pii macro and NEVER passed downstream in plaintext; names/phones/
-- addresses/IP/user-agent are dropped (never selected). Money stays in source
-- currency (*_src); FX to USD happens in the fact layer.
--
-- Payment fee (audit WOO_PAYLOAD_AUDIT §6): the processor fee lives in order
-- meta_data (_cs_stripe_fee / _cs_paypal_fee) in the PROCESSOR currency
-- (_cs_*_currency), NOT in fee_lines (those are customer tips). We surface the
-- raw plugin fee + its currency here; fact_order does the FX + seed fallback +
-- payment_fee_source assignment.

with src as (
    select
        o.site_code,
        o.woo_order_id,
        o._payload as p,
        o.status,
        o.currency,
        o.date_created_gmt
    from {{ source('raw', 'woo_orders') }} o
),

meta as (
    -- one pass over meta_data, pivot the keys we need
    select
        s.site_code,
        s.woo_order_id,
        max(case when m->>'key' = '_cs_stripe_fee'      then m->>'value' end) as stripe_fee_raw,
        max(case when m->>'key' = '_cs_stripe_currency'  then m->>'value' end) as stripe_currency,
        max(case when m->>'key' = '_cs_paypal_fee'      then m->>'value' end) as paypal_fee_raw,
        max(case when m->>'key' = '_cs_paypal_currency'  then m->>'value' end) as paypal_currency
    from src s
    left join lateral jsonb_array_elements(s.p->'meta_data') as m on true
    group by s.site_code, s.woo_order_id
),

typed as (
    select
        s.site_code,
        s.woo_order_id,
        s.site_code || '-' || s.woo_order_id::text                       as order_natural_key,
        s.p->>'number'                                                    as order_number,
        s.status,
        (s.status in ('cancelled', 'failed'))                            as status_is_cancelled,
        upper(coalesce(s.currency, s.p->>'currency'))                    as currency_source,
        s.date_created_gmt                                               as order_created_at_utc,
        s.date_created_gmt::date                                         as order_date,
        s.p->>'payment_method'                                           as payment_method,
        s.p->>'payment_method_title'                                     as payment_method_title,
        nullif(trim(upper(s.p->'billing'->>'country')), '')             as billing_country_code,

        -- money in source currency
        nullif(s.p->>'total',  '')::numeric                              as order_total_src,
        nullif(s.p->>'shipping_total', '')::numeric                      as shipping_charged_src,
        nullif(s.p->>'discount_total', '')::numeric                      as discount_src,
        nullif(s.p->>'total_tax', '')::numeric                           as tax_src,

        -- PII: hashed email only + unknown handling
        {{ hash_pii("s.p->'billing'->>'email'") }}                       as billing_email_hash,
        (nullif(trim(s.p->'billing'->>'email'), '') is null)            as is_unknown_email,

        -- plugin payment fee (processor currency); resolved fully in fact_order
        nullif(mt.stripe_fee_raw, '')::numeric                           as stripe_fee_src,
        nullif(mt.paypal_fee_raw, '')::numeric                           as paypal_fee_src,
        upper(mt.stripe_currency)                                        as stripe_currency,
        upper(mt.paypal_currency)                                        as paypal_currency
    from src s
    left join meta mt
        on mt.site_code = s.site_code and mt.woo_order_id = s.woo_order_id
)

select
    *,
    coalesce(stripe_fee_src, paypal_fee_src)                             as plugin_payment_fee_src,
    case
        when stripe_fee_src is not null then stripe_currency
        when paypal_fee_src is not null then paypal_currency
    end                                                                  as plugin_payment_fee_currency,
    (coalesce(stripe_fee_src, paypal_fee_src) is not null)              as has_plugin_payment_fee,
    -- guest checkout => linkage by hashed email only; unknowns get a per-order key
    coalesce(
        billing_email_hash,
        'unknown:' || site_code || ':' || woo_order_id::text
    )                                                                    as customer_hash
from typed
