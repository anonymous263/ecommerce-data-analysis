{{ config(materialized='table') }}

-- Country dimension. The country_iso_map seed only normalizes/enriches a
-- handful of codes, but orders span ~60 billing countries, so the dimension is
-- built from the DISTINCT billing countries actually present (already ISO
-- alpha-2 from Woo), LEFT JOINed to the seed for name/region/currency. Codes
-- absent from the seed keep the raw code and Unknown enrichment. A synthetic
-- 'XX' row absorbs orders with no billing country so every fact FK resolves.
-- country_sk is a surrogate over country_code.

with seed as (
    -- dedupe seed to one row per ISO country_code (source_country maps many->one)
    select
        country_code,
        max(country_name) as country_name,
        max(region)       as region,
        max(currency)     as currency
    from {{ ref('country_iso_map') }}
    group by country_code
),

order_countries as (
    select distinct coalesce(billing_country_code, 'XX') as country_code
    from {{ ref('stg_woo_orders') }}
),

all_codes as (
    select country_code from order_countries
    union
    select country_code from seed
)

select
    {{ dbt_utils.generate_surrogate_key(['a.country_code']) }} as country_sk,
    a.country_code,
    coalesce(s.country_name, case when a.country_code = 'XX' then 'Unknown' else a.country_code end) as country_name,
    coalesce(s.region, 'Unknown')                              as region,
    upper(s.currency)                                          as currency
from all_codes a
left join seed s on s.country_code = a.country_code
