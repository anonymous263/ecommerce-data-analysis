-- ============================================================================
-- Phase 1 — WooCommerce raw landing tables
-- ----------------------------------------------------------------------------
-- Owner: Python EL (extract/load only — NO business logic here).
-- Every table lands the source payload as-is:
--   * site_code     — multi-site discriminator (see config/sites.yaml)
--   * woo_<entity>_id — WooCommerce natural key
--   * extracted_at  — when this row was pulled (UTC)
--   * _payload      — full JSON response object, the JSON safety net (§9.4)
-- A handful of source fields are promoted to columns for watermarking and
-- cheap filtering. Promotion is a verbatim copy, not a transform; all typing,
-- FX, hashing, and joins happen later in dbt staging.
--
-- Idempotent load: PK on (site_code, woo_<entity>_id); loaders UPSERT so a
-- re-run over the same window updates in place and never duplicates.
-- Run once against Postgres:  psql ... -f sql/ddl/01_raw_woo.sql
-- ============================================================================

CREATE SCHEMA IF NOT EXISTS raw;

-- ---------------------------------------------------------------------------
-- Orders (line_items live inside _payload AND are exploded into woo_order_items)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw.woo_orders (
    site_code         TEXT        NOT NULL,
    woo_order_id      BIGINT      NOT NULL,
    number            TEXT,
    status            TEXT,
    currency          TEXT,
    date_created_gmt  TIMESTAMPTZ,
    date_modified_gmt TIMESTAMPTZ,          -- incremental watermark source (§3)
    extracted_at      TIMESTAMPTZ NOT NULL,
    _payload          JSONB       NOT NULL,
    PRIMARY KEY (site_code, woo_order_id)
);
CREATE INDEX IF NOT EXISTS ix_woo_orders_modified
    ON raw.woo_orders (site_code, date_modified_gmt);

-- ---------------------------------------------------------------------------
-- Order line items — exploded from orders[].line_items (grain: one item line)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw.woo_order_items (
    site_code          TEXT        NOT NULL,
    woo_order_id       BIGINT      NOT NULL,
    woo_order_item_id  BIGINT      NOT NULL,
    extracted_at       TIMESTAMPTZ NOT NULL,
    _payload           JSONB       NOT NULL,
    PRIMARY KEY (site_code, woo_order_id, woo_order_item_id)
);
CREATE INDEX IF NOT EXISTS ix_woo_order_items_order
    ON raw.woo_order_items (site_code, woo_order_id);

-- ---------------------------------------------------------------------------
-- Products
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw.woo_products (
    site_code         TEXT        NOT NULL,
    woo_product_id    BIGINT      NOT NULL,
    date_modified_gmt TIMESTAMPTZ,
    extracted_at      TIMESTAMPTZ NOT NULL,
    _payload          JSONB       NOT NULL,
    PRIMARY KEY (site_code, woo_product_id)
);

-- ---------------------------------------------------------------------------
-- Customers (PII stays in raw ONLY; dbt staging hashes/drops before marts)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw.woo_customers (
    site_code         TEXT        NOT NULL,
    woo_customer_id   BIGINT      NOT NULL,
    date_modified_gmt TIMESTAMPTZ,
    extracted_at      TIMESTAMPTZ NOT NULL,
    _payload          JSONB       NOT NULL,
    PRIMARY KEY (site_code, woo_customer_id)
);

-- ---------------------------------------------------------------------------
-- Refunds — order-level grain by default (§3; item-level only if audit confirms)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw.woo_refunds (
    site_code         TEXT        NOT NULL,
    woo_refund_id     BIGINT      NOT NULL,
    woo_order_id      BIGINT      NOT NULL,
    date_created_gmt  TIMESTAMPTZ,
    extracted_at      TIMESTAMPTZ NOT NULL,
    _payload          JSONB       NOT NULL,
    PRIMARY KEY (site_code, woo_refund_id)
);
CREATE INDEX IF NOT EXISTS ix_woo_refunds_order
    ON raw.woo_refunds (site_code, woo_order_id);

-- ---------------------------------------------------------------------------
-- Coupons
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw.woo_coupons (
    site_code         TEXT        NOT NULL,
    woo_coupon_id     BIGINT      NOT NULL,
    date_modified_gmt TIMESTAMPTZ,
    extracted_at      TIMESTAMPTZ NOT NULL,
    _payload          JSONB       NOT NULL,
    PRIMARY KEY (site_code, woo_coupon_id)
);

-- ---------------------------------------------------------------------------
-- Incremental high-watermark, per (site, entity). Advances only on a fully
-- successful paginated pull (§3). watermark = max date_modified_gmt seen.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw.pipeline_state (
    site_code    TEXT        NOT NULL,
    entity       TEXT        NOT NULL,
    watermark    TIMESTAMPTZ,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (site_code, entity)
);

-- ---------------------------------------------------------------------------
-- Run log — one row per EL run per site (§9.1)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw.pipeline_runs (
    run_id         UUID        NOT NULL DEFAULT gen_random_uuid(),
    pipeline_name  TEXT        NOT NULL,
    site_code      TEXT        NOT NULL,
    start_ts       TIMESTAMPTZ NOT NULL,
    end_ts         TIMESTAMPTZ,
    status         TEXT        NOT NULL DEFAULT 'running',  -- running | success | failed
    rows_in        INTEGER,
    rows_out       INTEGER,
    error_text     TEXT,
    PRIMARY KEY (run_id)
);
CREATE INDEX IF NOT EXISTS ix_pipeline_runs_site_start
    ON raw.pipeline_runs (site_code, start_ts DESC);
