-- Singular test: the seeded site list must match the canonical site configuration.
--
-- dbt/SQL cannot read config/sites.yaml directly, so the authoritative yaml <-> seed
-- field-parity check lives in tests/test_site_config_matches_seed.py (pytest). This
-- singular test guards the *loaded seed table* inside the warehouse and runs as part of
-- `dbt build` / `dbt test`.
--
-- Maintenance: keep the expected set below in sync with config/sites.yaml. When a site is
-- added/removed, update config/sites.yaml, dbt/seeds/dim_site_seed.csv, and this array; the
-- pytest will fail if the yaml and seed ever diverge.

with expected(site_code) as (
    values ('FOS')
),

seeded as (
    select site_code from {{ ref('dim_site_seed') }}
),

mismatches as (
    select site_code, 'missing_from_seed' as issue
    from expected
    where site_code not in (select site_code from seeded)

    union all

    select site_code, 'unexpected_in_seed' as issue
    from seeded
    where site_code not in (select site_code from expected)
)

select * from mismatches
