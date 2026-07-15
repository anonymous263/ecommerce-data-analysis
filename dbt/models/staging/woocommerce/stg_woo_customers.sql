{{ config(materialized='view') }}

-- Registered Woo customers, typed. PII (email) is hashed here; names/phones/
-- addresses are dropped. NOTE: this store is guest-checkout dominated and
-- raw.woo_customers is currently empty, so dim_customer_anonymized is built
-- from order billing emails (stg_woo_orders), not from this model. Kept for
-- completeness and future use.

with src as (
    select
        c.site_code,
        c.woo_customer_id,
        c._payload as p
    from {{ source('raw', 'woo_customers') }} c
)

select
    site_code,
    woo_customer_id,
    {{ hash_pii("p->>'email'") }}                          as customer_email_hash,
    nullif(trim(upper(p->'billing'->>'country')), '')     as billing_country_code,
    (p->>'date_created_gmt')::timestamptz                  as created_at_utc
from src
