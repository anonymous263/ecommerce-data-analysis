{{ config(materialized='table') }}

-- Site dimension, sourced from the dim_site_seed (mirrors config/sites.yaml;
-- a singular test asserts parity). site_sk is a surrogate over site_code.
--
-- `domain` is intentionally blank in the committed seed: storefront URLs are
-- private and resolved from the environment (see config/sites.yaml
-- `base_url_env`). The column is retained for downstream shape stability.

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
