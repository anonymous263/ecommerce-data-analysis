{{ config(materialized='table') }}

-- Site dimension, sourced from the dim_site_seed (mirrors config/sites.yaml;
-- a singular test asserts parity). site_sk is a surrogate over site_code.

select
    {{ dbt_utils.generate_surrogate_key(['site_code']) }} as site_sk,
    site_code,
    site_name,
    domain,
    upper(default_currency)       as default_currency,
    timezone,
    reporting_timezone,
    is_active
from {{ ref('dim_site_seed') }}
