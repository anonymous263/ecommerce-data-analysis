{{ config(materialized='table') }}

-- Anonymized customer dimension. Grain: one row per customer_hash. Carries NO
-- plaintext PII and NO aggregate behavior (that lives in mart_customer_summary
-- per DATA_MODEL §5.4). Built from order billing emails (raw.woo_customers is
-- empty; guest checkout). customer_hash = SHA-256(email||salt) or, for orders
-- with no email, 'unknown:<site>:<woo_order_id>' (is_unknown_email = true).
-- country_sk = billing country at first order.

with orders as (
    select
        customer_hash,
        is_unknown_email,
        order_date,
        coalesce(billing_country_code, 'XX') as country_code
    from {{ ref('stg_woo_orders') }}
),

first_seen as (
    select distinct on (customer_hash)
        customer_hash,
        country_code as first_country_code
    from orders
    order by customer_hash, order_date asc nulls last
),

agg as (
    select
        customer_hash,
        bool_and(is_unknown_email) as is_unknown_email,
        min(order_date)            as first_order_date,
        max(order_date)            as last_order_date
    from orders
    group by customer_hash
)

select
    {{ dbt_utils.generate_surrogate_key(['a.customer_hash']) }}   as customer_sk,
    a.customer_hash,
    a.is_unknown_email,
    {{ dbt_utils.generate_surrogate_key(['f.first_country_code']) }} as country_sk,
    a.first_order_date,
    a.last_order_date
from agg a
left join first_seen f on f.customer_hash = a.customer_hash
