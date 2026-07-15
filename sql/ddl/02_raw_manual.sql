-- ============================================================================
-- Phase 3 — Manual Order Management raw landing table
-- ----------------------------------------------------------------------------
-- Owner: Python EL (extract/load only — NO business logic here).
-- Source: data/raw/manual/order_management.csv (Google Sheet export, gitignored).
--
-- Grain: ONE row per Woo order (site_code + woo_order_id). The sheet is
-- physically at line-item grain (multi-item orders repeat the item columns per
-- row and populate the order-level columns only on the first row); the loader
-- forward-fills order-level columns by Order Code and dedupes to the first row
-- per order before landing here.
--
-- Privacy (hard rule — docs/PIPELINE_DESIGN.md §5, CLAUDE.md): PII columns
-- (Name, Email, Phone, Ship to) are DROPPED before this table is written, so
-- this is NOT a byte-for-byte copy of the sheet. Tracking IDs / fulfilment URLs
-- may land in _payload but are hashed only in Phase 5 staging (never surfaced
-- in Phase 3 staging/marts).
--
-- Currency: the loader trusts the sheet's Currency column only and strips
-- currency symbols/mojibake before parsing. Order-currency amounts land as
-- *_src (FX->USD happens in dbt using the order date); already-USD amounts
-- (CoGS, Design fee, Revenue, Profit) land directly.
--
-- Refresh semantics: TRUNCATE-and-reload each run (snapshot — deleted sheet
-- rows propagate). Not an incremental upsert.
-- Run once against Postgres:  psql ... -f sql/ddl/02_raw_manual.sql
-- ============================================================================

CREATE SCHEMA IF NOT EXISTS raw;

CREATE TABLE IF NOT EXISTS raw.csv_order_management (
    site_code                 TEXT        NOT NULL,
    woo_order_id              BIGINT      NOT NULL,
    order_status              TEXT,                 -- CSV 'Status'
    order_date                DATE,                 -- CSV 'Date' (MM/DD/YYYY)
    currency                  TEXT,                 -- CSV 'Currency' (trusted verbatim)

    -- order-currency numerics (source currency; FX->USD happens in dbt)
    items_subtotal_src        NUMERIC,              -- CSV 'Items Subtotal'
    csv_shipping_charged_src  NUMERIC,              -- CSV 'Shipping' = CUSTOMER shipping charge (recon only)
    tips_coupon_src           NUMERIC,              -- CSV 'Típs/Coupon'
    order_total_src           NUMERIC,              -- CSV 'Total'
    fee_src                   NUMERIC,              -- CSV 'Fee' -> payment_fee_fallback (order currency)
    payout_src                NUMERIC,              -- CSV 'Payout'

    -- already-USD numerics (parsed directly, NO FX)
    cogs_usd                  NUMERIC,              -- CSV 'CoGS' — includes supplier fulfilment/shipping fee
    design_fee_usd            NUMERIC,              -- CSV 'Design fee'
    csv_revenue_observed_usd  NUMERIC,              -- CSV 'Revenue' — recon only, NEVER official
    csv_profit_observed_usd   NUMERIC,              -- CSV 'Profit'  — recon only, NEVER official
    csv_roi                   NUMERIC,              -- CSV 'ROI' ratio — recon only
    csv_profit_margin         NUMERIC,              -- CSV 'Profit Margin' ratio — recon only

    country                   TEXT,                 -- CSV 'Country'
    extracted_at              TIMESTAMPTZ NOT NULL,
    _payload                  JSONB       NOT NULL, -- cleaned, PII-dropped source row
    PRIMARY KEY (site_code, woo_order_id)
);
CREATE INDEX IF NOT EXISTS ix_csv_order_management_order
    ON raw.csv_order_management (site_code, woo_order_id);
