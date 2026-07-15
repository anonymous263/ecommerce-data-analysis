"""Phase 3 — Manual Order Management CSV raw ingestion.

Reads the manually maintained ``Order Management.csv`` (a Google Sheet export),
drops PII, forward-fills order-level columns onto multi-item child rows, dedupes
to order grain, and TRUNCATE-reloads ``raw.csv_order_management``. Extract/load
ONLY: this module parses/cleans and drops PII — all typing/FX/joins/hashing
happen later in dbt (docs/PIPELINE_DESIGN.md §5).

Design invariants:
  * PII (Name, Email, Phone, Ship to) is DROPPED before anything is written, so
    ``raw.csv_order_management`` is NOT a byte-for-byte copy of the sheet.
  * The two sub-header rows under the real header are skipped (``skiprows=[1,2]``).
  * Order-level columns are populated only on the FIRST physical row of each
    order; they are forward-filled by ``Order Code`` then deduped to one row per
    ``(site_code, woo_order_id)`` (fact_order_cost is at order grain).
  * Currency is trusted from the sheet's ``Currency`` column only; currency
    symbols / mojibake are stripped before parsing numbers.
  * Refresh = TRUNCATE-and-reload (snapshot semantics; deleted rows propagate).

Run:  python -m src.extract.csv_order_management [--apply-ddl] [--csv-path PATH]
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import Engine, text

from src.load.db import apply_sql_file, make_engine
from src.load.upsert import upsert_rows
from src.utils.logging import get_logger

logger = get_logger(__name__)

PIPELINE_NAME = "csv_order_management"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_DDL_PATH = PROJECT_ROOT / "sql" / "ddl" / "02_raw_manual.sql"
DEFAULT_CSV_PATH = PROJECT_ROOT / "data" / "raw" / "manual" / "order_management.csv"

RAW_TABLE = "raw.csv_order_management"
CONFLICT_COLS = ("site_code", "woo_order_id")

# The real header is row 0; the next two physical rows are sub-header / grand-
# total rows the sheet owner will not hand-edit away, so we skip them by index.
SKIP_ROWS = [1, 2]

# PII dropped BEFORE writing to raw (hard privacy rule). Compared post-normalise.
PII_COLUMNS = frozenset({"Name", "Email", "Phone", "Ship to"})

# Item-level columns repeat on every physical row of a multi-item order; every
# other column is order-level and is forward-filled by Order Code.
ITEM_LEVEL_COLUMNS = frozenset(
    {"Date", "Day", "Month", "Year", "Status", "Project", "Order Code",
     "Product name", "Product URL", "Type"}
)

# Normalised CSV column -> raw.csv_order_management column, split by parse kind.
ORDER_CURRENCY_COLUMNS = {  # order currency -> *_src (FX in dbt)
    "Items Subtotal": "items_subtotal_src",
    "Shipping": "csv_shipping_charged_src",   # customer shipping charge (recon only)
    "Tips/Coupon": "tips_coupon_src",         # 'Típs/Coupon' after ASCII-fold
    "Total": "order_total_src",
    "Fee": "fee_src",                          # -> payment_fee_fallback in dbt
    "Payout": "payout_src",
}
USD_MONEY_COLUMNS = {  # already USD -> parse directly, NO FX
    "CoGS": "cogs_usd",                        # includes supplier fulfilment/shipping fee
    "Design fee": "design_fee_usd",
    "Revenue": "csv_revenue_observed_usd",     # recon only
    "Profit": "csv_profit_observed_usd",       # recon only
}
PERCENT_COLUMNS = {  # ratios -> recon only
    "ROI": "csv_roi",
    "Profit Margin": "csv_profit_margin",
}


# ---------------------------------------------------------------------------
# Pure parsers / cleaners (no I/O; unit-tested in tests/test_csv_order_management.py)
# ---------------------------------------------------------------------------
def ascii_fold(value: Any) -> str:
    """Strip diacritics/combining marks and surrounding whitespace.

    ``'Típs/Coupon'`` -> ``'Tips/Coupon'``, ``' Shipping Company '`` ->
    ``'Shipping Company'``. Used to normalise header names so the currency
    mojibake in the source header cannot break column mapping.
    """
    text_value = unicodedata.normalize("NFKD", str(value))
    without_marks = "".join(ch for ch in text_value if not unicodedata.combining(ch))
    return without_marks.strip()


def parse_money(value: Any) -> float | None:
    """Parse a money cell, stripping currency symbols/mojibake/commas.

    Trusts the sheet's Currency column, so the symbol itself is discarded and
    never used to infer currency. Handles ``-$0.92`` and ``($0.92)`` as
    negatives and ``"$159,548.24"`` thousands separators. Blank -> ``None``.
    """
    if value is None:
        return None
    raw = str(value).strip()
    if not raw or raw.lower() == "nan":
        return None
    is_parenthesised = raw.startswith("(") and raw.endswith(")")
    cleaned = re.sub(r"[^0-9.\-]", "", raw)
    if cleaned in ("", "-", ".", "-.", "--"):
        return None
    try:
        number = float(cleaned)
    except ValueError:
        return None
    if is_parenthesised:
        number = -abs(number)
    return number


def parse_percent(value: Any) -> float | None:
    """Parse a percentage cell (e.g. ``'43.57%'``) into a ratio (``0.4357``)."""
    number = parse_money(value)
    return number / 100.0 if number is not None else None


def parse_order_code(value: Any) -> int | None:
    """Parse ``Order Code`` as a plain integer ``woo_order_id``; else ``None``.

    Blank / non-numeric (sub-header text, empty child rows) -> ``None`` so the
    caller skips the row. Tolerates pandas float coercion (``'73874.0'``).
    """
    if value is None:
        return None
    raw = str(value).strip().replace(",", "")
    if not raw or raw.lower() == "nan":
        return None
    try:
        return int(float(raw))
    except ValueError:
        return None


def parse_order_date(value: Any) -> date | None:
    """Parse the sheet's ``Date`` (``MM/DD/YYYY``) into a ``date``; else ``None``."""
    if value is None:
        return None
    raw = str(value).strip()
    if not raw or raw.lower() == "nan":
        return None
    parsed = pd.to_datetime(raw, format="%m/%d/%Y", errors="coerce")
    return None if pd.isna(parsed) else parsed.date()


def _clean_cell(value: Any) -> str | None:
    """Return a trimmed string for the JSON payload, or ``None`` for blanks."""
    if value is None:
        return None
    raw = str(value).strip()
    if not raw or raw.lower() == "nan":
        return None
    return raw


# ---------------------------------------------------------------------------
# DataFrame-level transforms
# ---------------------------------------------------------------------------
def normalize_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Return ``frame`` with ASCII-folded, whitespace-trimmed column names."""
    return frame.rename(columns={col: ascii_fold(col) for col in frame.columns})


def drop_pii_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Drop PII columns (Name/Email/Phone/Ship to) BEFORE anything is written."""
    present = [col for col in frame.columns if col in PII_COLUMNS]
    return frame.drop(columns=present)


def forward_fill_order_level(frame: pd.DataFrame) -> pd.DataFrame:
    """Forward-fill order-level columns within each ``Order Code`` group.

    Order-level columns are blank on multi-item child rows; grouping by
    ``Order Code`` and forward-filling copies the first row's whole-order totals
    down onto its child rows. Item-level columns are left untouched.
    """
    if "Order Code" not in frame.columns:
        return frame
    order_level = [
        col for col in frame.columns
        if col not in ITEM_LEVEL_COLUMNS and col != "Order Code"
    ]
    if not order_level:
        return frame
    filled = frame.copy()
    # The CSV is read with keep_default_na=False, so blank child-row cells are
    # empty strings, not NaN; mask them to NA so ffill actually copies the first
    # row's totals down, then restore any still-unfilled blanks to "".
    masked = filled[order_level].replace(r"^\s*$", pd.NA, regex=True)
    filled[order_level] = masked.groupby(filled["Order Code"]).ffill().fillna("")
    return filled


def _row_payload(row: "pd.Series[Any]") -> dict[str, Any]:
    """Cleaned (already PII-dropped) source row as a JSON-able dict."""
    payload: dict[str, Any] = {}
    for col, value in row.items():
        cleaned = _clean_cell(value)
        if cleaned is not None:
            payload[str(col)] = cleaned
    return payload


def _to_raw_row(row: "pd.Series[Any]", woo_order_id: int, extracted_at: datetime) -> dict[str, Any]:
    """Map one (order-grain) sheet row to a raw.csv_order_management row dict."""
    def money(col: str) -> float | None:
        return parse_money(row[col]) if col in row.index else None

    def percent(col: str) -> float | None:
        return parse_percent(row[col]) if col in row.index else None

    def textval(col: str) -> str | None:
        return _clean_cell(row[col]) if col in row.index else None

    raw_row: dict[str, Any] = {
        "site_code": textval("Project"),
        "woo_order_id": woo_order_id,
        "order_status": textval("Status"),
        "order_date": parse_order_date(row["Date"]) if "Date" in row.index else None,
        "currency": textval("Currency"),
        "country": textval("Country"),
        "extracted_at": extracted_at,
        "_payload": _row_payload(row),
    }
    for csv_col, out_col in ORDER_CURRENCY_COLUMNS.items():
        raw_row[out_col] = money(csv_col)
    for csv_col, out_col in USD_MONEY_COLUMNS.items():
        raw_row[out_col] = money(csv_col)
    for csv_col, out_col in PERCENT_COLUMNS.items():
        raw_row[out_col] = percent(csv_col)
    return raw_row


def build_raw_rows(frame: pd.DataFrame, extracted_at: datetime) -> list[dict[str, Any]]:
    """Transform a raw sheet DataFrame into order-grain raw rows.

    Pipeline: normalise headers -> drop PII -> forward-fill order-level columns
    -> for each row with a numeric ``Order Code`` and a ``Project`` (site) code,
    emit one row, keeping only the FIRST occurrence per ``(site_code, order)``.
    """
    normalised = forward_fill_order_level(drop_pii_columns(normalize_columns(frame)))

    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for _, row in normalised.iterrows():
        woo_order_id = parse_order_code(row["Order Code"]) if "Order Code" in row.index else None
        if woo_order_id is None:
            continue
        site_code = _clean_cell(row["Project"]) if "Project" in row.index else None
        if site_code is None:
            continue
        key = (site_code, woo_order_id)
        if key in seen:  # keep first row per order (order-grain dedupe)
            continue
        seen.add(key)
        rows.append(_to_raw_row(row, woo_order_id, extracted_at))
    return rows


def read_csv(csv_path: Path) -> pd.DataFrame:
    """Read the sheet export, skipping the two sub-header rows (all-text dtype)."""
    return pd.read_csv(csv_path, skiprows=SKIP_ROWS, dtype=str, keep_default_na=False)


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------
def resolve_csv_path(env: dict[str, str] | None = None) -> Path:
    """Resolve the CSV path from ``CSV_ORDER_MANAGEMENT_PATH`` or the default."""
    source = env if env is not None else os.environ
    configured = source.get("CSV_ORDER_MANAGEMENT_PATH", "").strip()
    return Path(configured) if configured else DEFAULT_CSV_PATH


def truncate_reload(engine: Engine, rows: list[dict[str, Any]]) -> int:
    """TRUNCATE ``raw.csv_order_management`` and bulk-insert ``rows``.

    Snapshot semantics: a truncate-reload makes rows deleted from the sheet
    disappear from raw (unlike an incremental upsert). TRUNCATE and the insert
    run in ONE transaction (``truncate_first=True``) so a mid-load failure
    rolls back to the prior good snapshot instead of leaving the table empty.
    Returns rows written.
    """
    return upsert_rows(engine, RAW_TABLE, rows, CONFLICT_COLS, truncate_first=True)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manual Order Management CSV ingestion (Phase 3)")
    parser.add_argument("--apply-ddl", action="store_true", help="Apply sql/ddl/02_raw_manual.sql first")
    parser.add_argument("--csv-path", help="Override CSV_ORDER_MANAGEMENT_PATH / the default path")
    args = parser.parse_args(argv)

    load_dotenv()
    engine = make_engine()

    if args.apply_ddl:
        apply_sql_file(engine, RAW_DDL_PATH)

    csv_path = Path(args.csv_path) if args.csv_path else resolve_csv_path()
    if not csv_path.exists():
        logger.error("CSV not found: %s", csv_path)
        return 1

    extracted_at = datetime.now(timezone.utc)
    frame = read_csv(csv_path)
    rows = build_raw_rows(frame, extracted_at)
    written = truncate_reload(engine, rows)
    logger.info("Loaded %d order-grain rows into %s from %s", written, RAW_TABLE, csv_path.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
