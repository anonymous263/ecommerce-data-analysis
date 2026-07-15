{{ config(materialized='table') }}

-- Payment method dimension from distinct Woo payment_method codes. A synthetic
-- 'unknown' row absorbs orders missing a payment_method so the FK resolves.
-- payment_method_sk is a surrogate over method_code.

with methods as (
    select
        coalesce(nullif(trim(payment_method), ''), 'unknown') as method_code,
        max(payment_method_title)                             as method_name
    from {{ ref('stg_woo_orders') }}
    group by 1
)

select
    {{ dbt_utils.generate_surrogate_key(['method_code']) }} as payment_method_sk,
    method_code,
    coalesce(method_name, method_code) as method_name
from methods
