"""Phase 1 — WooCommerce raw ingestion.

Pulls orders (+ per-order refunds), products, customers, and coupons for every
active site in ``config/sites.yaml`` and lands them into the ``raw.woo_*``
tables. Extract/load ONLY: this module copies the API payload verbatim and
computes no business metrics — all typing/FX/hashing/joins happen in dbt.

Design invariants (docs/PIPELINE_DESIGN.md §3):
  * Incremental high-watermark on ``date_modified_gmt``, in ``raw.pipeline_state``.
  * Idempotent upsert on ``(site_code, woo_<entity>_id)``.
  * Watermark advances only after a fully successful paginated pull.
  * Every run is logged to ``raw.pipeline_runs``.

Run:  python -m src.extract.woo_api [--site FOS] [--apply-ddl] [--full-refresh]
"""
from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from sqlalchemy import Engine, text

from src.load.db import apply_sql_file, make_engine
from src.load.upsert import DEFAULT_JSON_COLUMNS, _encode_row, build_upsert_sql, upsert_rows
from src.utils.config import Site, load_sites, resolve_credentials
from src.utils.http import make_client, paginate
from src.utils.logging import get_logger

logger = get_logger(__name__)

PIPELINE_NAME = "woo_api"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_DDL_PATH = PROJECT_ROOT / "sql" / "ddl" / "01_raw_woo.sql"

# WooCommerce's modified_after filter is exclusive (strictly greater-than), so
# an order modified in the exact same second as the stored watermark could be
# skipped forever. Re-query from a small overlap; the idempotent upsert (and,
# for order_items, the delete-then-insert in _load_order_items) makes the
# harmless boundary re-pull a no-op duplicate rather than a gap.
WATERMARK_OVERLAP_SECONDS = 1
WATERMARK_OVERLAP = timedelta(seconds=WATERMARK_OVERLAP_SECONDS)

# Full-pull list endpoints (products/customers/coupons) upsert in batches of this
# size as pages stream in, bounding memory for large catalogues (e.g. 58k products).
STREAM_BATCH_SIZE = 500

# entity -> (raw table, conflict/PK columns)
ENTITY_TARGETS: dict[str, tuple[str, tuple[str, ...]]] = {
    "orders": ("raw.woo_orders", ("site_code", "woo_order_id")),
    "order_items": ("raw.woo_order_items", ("site_code", "woo_order_id", "woo_order_item_id")),
    "products": ("raw.woo_products", ("site_code", "woo_product_id")),
    "customers": ("raw.woo_customers", ("site_code", "woo_customer_id")),
    "refunds": ("raw.woo_refunds", ("site_code", "woo_refund_id")),
    "coupons": ("raw.woo_coupons", ("site_code", "woo_coupon_id")),
}


# ---------------------------------------------------------------------------
# Pure payload -> raw row mappers (no I/O; unit-tested in tests/test_woo_api.py)
# ---------------------------------------------------------------------------
def parse_gmt(value: Any) -> datetime | None:
    """Parse a WooCommerce ``*_gmt`` timestamp string as UTC. ``None``/blank -> None."""
    if not value:
        return None
    text_value = str(value).strip()
    if not text_value:  # whitespace-only timestamp -> treat as absent
        return None
    if text_value.endswith("Z"):
        text_value = text_value[:-1]
    parsed = datetime.fromisoformat(text_value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def to_order_row(order: dict[str, Any], site_code: str, extracted_at: datetime) -> dict[str, Any]:
    return {
        "site_code": site_code,
        "woo_order_id": int(order["id"]),
        "number": order.get("number"),
        "status": order.get("status"),
        "currency": order.get("currency"),
        "date_created_gmt": parse_gmt(order.get("date_created_gmt")),
        "date_modified_gmt": parse_gmt(order.get("date_modified_gmt")),
        "extracted_at": extracted_at,
        "_payload": order,
    }


def to_order_item_rows(order: dict[str, Any], site_code: str, extracted_at: datetime) -> list[dict[str, Any]]:
    """Explode ``order.line_items[]`` into one raw row per line."""
    order_id = int(order["id"])
    rows: list[dict[str, Any]] = []
    for item in order.get("line_items", []) or []:
        rows.append(
            {
                "site_code": site_code,
                "woo_order_id": order_id,
                "woo_order_item_id": int(item["id"]),
                "extracted_at": extracted_at,
                "_payload": item,
            }
        )
    return rows


def to_product_row(product: dict[str, Any], site_code: str, extracted_at: datetime) -> dict[str, Any]:
    return {
        "site_code": site_code,
        "woo_product_id": int(product["id"]),
        "date_modified_gmt": parse_gmt(product.get("date_modified_gmt")),
        "extracted_at": extracted_at,
        "_payload": product,
    }


def to_customer_row(customer: dict[str, Any], site_code: str, extracted_at: datetime) -> dict[str, Any]:
    return {
        "site_code": site_code,
        "woo_customer_id": int(customer["id"]),
        "date_modified_gmt": parse_gmt(customer.get("date_modified_gmt")),
        "extracted_at": extracted_at,
        "_payload": customer,
    }


def to_coupon_row(coupon: dict[str, Any], site_code: str, extracted_at: datetime) -> dict[str, Any]:
    return {
        "site_code": site_code,
        "woo_coupon_id": int(coupon["id"]),
        "date_modified_gmt": parse_gmt(coupon.get("date_modified_gmt")),
        "extracted_at": extracted_at,
        "_payload": coupon,
    }


def to_refund_row(
    refund: dict[str, Any], order_id: int, site_code: str, extracted_at: datetime
) -> dict[str, Any]:
    return {
        "site_code": site_code,
        "woo_refund_id": int(refund["id"]),
        "woo_order_id": order_id,
        "date_created_gmt": parse_gmt(refund.get("date_created_gmt")),
        "extracted_at": extracted_at,
        "_payload": refund,
    }


def max_watermark(orders: list[dict[str, Any]]) -> datetime | None:
    """Highest ``date_modified_gmt`` across a batch of order payloads."""
    stamps = [parse_gmt(o.get("date_modified_gmt")) for o in orders]
    present = [s for s in stamps if s is not None]
    return max(present) if present else None


# ---------------------------------------------------------------------------
# Watermark / run-log persistence
# ---------------------------------------------------------------------------
def read_watermark(engine: Engine, site_code: str, entity: str) -> datetime | None:
    sql = text(
        "SELECT watermark FROM raw.pipeline_state WHERE site_code = :site_code AND entity = :entity"
    )
    with engine.connect() as conn:
        row = conn.execute(sql, {"site_code": site_code, "entity": entity}).first()
    return row[0] if row else None


def write_watermark(engine: Engine, site_code: str, entity: str, watermark: datetime) -> None:
    sql = text(
        """
        INSERT INTO raw.pipeline_state (site_code, entity, watermark, updated_at)
        VALUES (:site_code, :entity, :watermark, now())
        ON CONFLICT (site_code, entity)
        DO UPDATE SET watermark = EXCLUDED.watermark, updated_at = now()
        """
    )
    with engine.begin() as conn:
        conn.execute(sql, {"site_code": site_code, "entity": entity, "watermark": watermark})


def start_run(engine: Engine, site_code: str, start_ts: datetime) -> str:
    sql = text(
        """
        INSERT INTO raw.pipeline_runs (pipeline_name, site_code, start_ts, status)
        VALUES (:pipeline_name, :site_code, :start_ts, 'running')
        RETURNING run_id
        """
    )
    with engine.begin() as conn:
        run_id = conn.execute(
            sql, {"pipeline_name": PIPELINE_NAME, "site_code": site_code, "start_ts": start_ts}
        ).scalar_one()
    return str(run_id)


def finish_run(
    engine: Engine,
    run_id: str,
    *,
    status: str,
    rows_out: int,
    end_ts: datetime,
    error_text: str | None = None,
) -> None:
    sql = text(
        """
        UPDATE raw.pipeline_runs
        SET status = :status, rows_out = :rows_out, end_ts = :end_ts, error_text = :error_text
        WHERE run_id = :run_id
        """
    )
    with engine.begin() as conn:
        conn.execute(
            sql,
            {
                "run_id": run_id,
                "status": status,
                "rows_out": rows_out,
                "end_ts": end_ts,
                "error_text": error_text,
            },
        )


# ---------------------------------------------------------------------------
# Per-site orchestration
# ---------------------------------------------------------------------------
def extract_site(site: Site, engine: Engine, *, full_refresh: bool = False) -> int:
    """Pull every entity for one site and land it. Returns total rows upserted."""
    creds = resolve_credentials(site)
    start_ts = datetime.now(timezone.utc)
    run_id = start_run(engine, site.site_code, start_ts)
    rows_out = 0
    try:
        with make_client(site.base_url, creds.key, creds.secret) as client:
            rows_out += _extract_orders_and_refunds(site, engine, client, full_refresh=full_refresh)
            rows_out += _extract_simple(site, engine, client, "products", to_product_row)
            rows_out += _extract_simple(site, engine, client, "customers", to_customer_row)
            rows_out += _extract_simple(site, engine, client, "coupons", to_coupon_row)
    except Exception as exc:  # noqa: BLE001 — log full failure to the run table, then re-raise
        finish_run(
            engine, run_id, status="failed", rows_out=rows_out,
            end_ts=datetime.now(timezone.utc), error_text=repr(exc),
        )
        logger.exception("Extract failed for site %s", site.site_code)
        raise

    finish_run(engine, run_id, status="success", rows_out=rows_out, end_ts=datetime.now(timezone.utc))
    logger.info("Site %s complete: %d rows upserted", site.site_code, rows_out)
    return rows_out


def _extract_orders_and_refunds(
    site: Site, engine: Engine, client: httpx.Client, *, full_refresh: bool
) -> int:
    watermark = None if full_refresh else read_watermark(engine, site.site_code, "orders")
    # dates_are_gmt=true makes Woo interpret modified_after as GMT, matching our
    # GMT watermark (date_modified_gmt). Without it Woo would read the filter in
    # the site's local timezone and silently skip or re-pull a window of orders.
    params: dict[str, Any] = {"orderby": "modified", "order": "asc", "dates_are_gmt": "true"}
    if watermark is not None:
        # modified_after is exclusive (strictly >); subtract a small overlap so
        # an order modified in the same second as the watermark is re-included
        # rather than permanently skipped. The re-pull is deduped by the upsert.
        query_from = watermark - WATERMARK_OVERLAP
        params["modified_after"] = query_from.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    orders = list(paginate(client, "/orders", params))
    extracted_at = datetime.now(timezone.utc)

    order_table, order_conflict = ENTITY_TARGETS["orders"]
    refund_table, refund_conflict = ENTITY_TARGETS["refunds"]

    rows_out = 0
    rows_out += upsert_rows(
        engine, order_table, [to_order_row(o, site.site_code, extracted_at) for o in orders], order_conflict
    )

    rows_out += _load_order_items(engine, site.site_code, orders, extracted_at)

    refund_rows: list[dict[str, Any]] = []
    for order in orders:
        # The order payload carries a `refunds` summary array; only orders with
        # a non-empty summary need the (slow) per-order /refunds sub-request. This
        # avoids one GET per order across the whole store (e.g. 4757 -> 34).
        if not order.get("refunds"):
            continue
        order_id = int(order["id"])
        refunds = list(paginate(client, f"/orders/{order_id}/refunds"))
        refund_rows.extend(
            to_refund_row(r, order_id, site.site_code, extracted_at) for r in refunds
        )
    rows_out += upsert_rows(engine, refund_table, refund_rows, refund_conflict)

    # Watermark advances only after the full pull above succeeded.
    new_watermark = max_watermark(orders)
    if new_watermark is not None:
        write_watermark(engine, site.site_code, "orders", new_watermark)
    return rows_out


def _load_order_items(
    engine: Engine, site_code: str, orders: list[dict[str, Any]], extracted_at: datetime
) -> int:
    """Authoritatively replace ``raw.woo_order_items`` for the pulled order ids.

    A plain upsert of the current ``line_items[]`` would leave a deleted line
    item's old row orphaned when an order is later edited to remove it, which
    would make dbt over-count quantities. Instead, within one transaction:
    DELETE every existing item row for the pulled order ids, then INSERT the
    current line items. A no-op (no DELETE, no INSERT) when ``orders`` is empty.
    """
    item_table, _ = ENTITY_TARGETS["order_items"]
    order_ids = [int(o["id"]) for o in orders]
    if not order_ids:
        return 0

    item_rows: list[dict[str, Any]] = []
    for order in orders:
        item_rows.extend(to_order_item_rows(order, site_code, extracted_at))

    delete_sql = text(
        f"DELETE FROM {item_table} WHERE site_code = :site_code AND woo_order_id = ANY(:order_ids)"
    )
    with engine.begin() as conn:
        conn.execute(delete_sql, {"site_code": site_code, "order_ids": order_ids})
        if item_rows:
            columns = list(item_rows[0].keys())
            insert_sql = build_upsert_sql(item_table, columns, ["site_code", "woo_order_id", "woo_order_item_id"])
            params = [_encode_row(row, DEFAULT_JSON_COLUMNS) for row in item_rows]
            conn.execute(text(insert_sql), params)

    logger.info(
        "Replaced order_items for %d order(s) (%d item rows) in %s", len(order_ids), len(item_rows), item_table
    )
    return len(item_rows)


def _extract_simple(
    site: Site,
    engine: Engine,
    client: httpx.Client,
    entity: str,
    mapper: Callable[[dict[str, Any], str, datetime], dict[str, Any]],
) -> int:
    """Full-pull a list endpoint (products/customers/coupons), streaming pages.

    Rows are upserted in batches of ``STREAM_BATCH_SIZE`` as pages arrive, so a
    large catalogue (e.g. 58k products) never loads fully into memory and each
    batch commits independently — a mid-run stop loses at most one batch, which
    the idempotent upsert re-lands on the next run.
    """
    table, conflict = ENTITY_TARGETS[entity]
    extracted_at = datetime.now(timezone.utc)
    total = 0
    batch: list[dict[str, Any]] = []
    for record in paginate(client, f"/{entity}"):
        batch.append(mapper(record, site.site_code, extracted_at))
        if len(batch) >= STREAM_BATCH_SIZE:
            total += upsert_rows(engine, table, batch, conflict)
            batch = []
    if batch:
        total += upsert_rows(engine, table, batch, conflict)
    return total


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="WooCommerce raw ingestion (Phase 1)")
    parser.add_argument("--site", help="Only run this site_code (default: all active sites)")
    parser.add_argument("--apply-ddl", action="store_true", help="Apply sql/ddl/01_raw_woo.sql first")
    parser.add_argument("--full-refresh", action="store_true", help="Ignore the stored watermark")
    args = parser.parse_args(argv)

    load_dotenv()
    engine = make_engine()

    if args.apply_ddl:
        apply_sql_file(engine, RAW_DDL_PATH)

    sites = load_sites(active_only=True)
    if args.site:
        sites = [s for s in sites if s.site_code == args.site]
        if not sites:
            logger.error("No active site named %s", args.site)
            return 1

    total = 0
    for site in sites:
        total += extract_site(site, engine, full_refresh=args.full_refresh)
    logger.info("All done: %d rows upserted across %d site(s)", total, len(sites))
    return 0


if __name__ == "__main__":
    sys.exit(main())
