"""Phase 3 manual CSV extractor — DB-free unit tests.

Covers the pure parsers (money/percent/order-code/date), header normalisation,
PII drop, forward-fill by Order Code, multi-item -> order-grain dedupe, currency
symbol stripping, USD-vs-order-currency column classification, and the sub-header
skip. No Postgres and no filesystem CSV are touched (frames built in memory).
"""
from __future__ import annotations

import io
from datetime import date, datetime, timezone

import pandas as pd
import pytest

from src.extract import csv_order_management as cim

FIXED_TS = datetime(2026, 7, 15, 8, 0, 0, tzinfo=timezone.utc)


# --- ascii_fold / header normalisation -------------------------------------
def test_ascii_fold_strips_diacritics_and_whitespace():
    assert cim.ascii_fold("Típs/Coupon") == "Tips/Coupon"
    assert cim.ascii_fold(" Shipping Company ") == "Shipping Company"


def test_normalize_columns_folds_mojibake_header():
    frame = pd.DataFrame(columns=["Típs/Coupon", " Shipping Company ", "CoGS"])
    normalised = cim.normalize_columns(frame)
    assert list(normalised.columns) == ["Tips/Coupon", "Shipping Company", "CoGS"]


# --- parse_money ------------------------------------------------------------
def test_parse_money_strips_currency_symbols_and_commas():
    assert cim.parse_money("$14.07") == 14.07
    assert cim.parse_money("$159,548.24") == 159548.24
    assert cim.parse_money("4,499") == 4499.0


def test_parse_money_handles_negatives_and_parentheses():
    assert cim.parse_money("-$0.92") == -0.92
    assert cim.parse_money("($0.92)") == -0.92


def test_parse_money_ignores_currency_symbol_never_infers_currency():
    # £/€/$ all strip to the same number — currency comes from the Currency column.
    assert cim.parse_money("£10.00") == 10.0
    assert cim.parse_money("€10.00") == 10.0
    assert cim.parse_money("$10.00") == 10.0


def test_parse_money_blank_is_none():
    assert cim.parse_money("") is None
    assert cim.parse_money("   ") is None
    assert cim.parse_money(None) is None
    assert cim.parse_money("nan") is None


def test_parse_percent_returns_ratio():
    assert cim.parse_percent("43.57%") == pytest.approx(0.4357)
    assert cim.parse_percent("-6.53%") == pytest.approx(-0.0653)
    assert cim.parse_percent("") is None


# --- parse_order_code -------------------------------------------------------
def test_parse_order_code_accepts_integers_and_float_coercion():
    assert cim.parse_order_code("73874") == 73874
    assert cim.parse_order_code("73874.0") == 73874
    assert cim.parse_order_code("1,234") == 1234


def test_parse_order_code_rejects_blank_and_non_numeric():
    assert cim.parse_order_code("") is None
    assert cim.parse_order_code("Items Information") is None
    assert cim.parse_order_code(None) is None
    assert cim.parse_order_code("nan") is None


def test_parse_order_date_reads_us_format():
    assert cim.parse_order_date("03/28/2023") == date(2023, 3, 28)
    assert cim.parse_order_date("") is None
    assert cim.parse_order_date("not-a-date") is None


# --- drop PII ---------------------------------------------------------------
def test_drop_pii_columns_removes_name_email_phone_shipto():
    frame = pd.DataFrame(
        {"Order Code": ["1"], "Name": ["x"], "Email": ["a@b.c"],
         "Phone": ["123"], "Ship to": ["addr"], "CoGS": ["$1"]}
    )
    cleaned = cim.drop_pii_columns(frame)
    assert list(cleaned.columns) == ["Order Code", "CoGS"]


# --- forward fill by Order Code --------------------------------------------
def _two_item_order() -> pd.DataFrame:
    # Row 1 carries order-level totals; row 2 is a child item row (blanks).
    return pd.DataFrame(
        [
            {"Order Code": "100", "Product name": "Tee", "Currency": "USD",
             "Total": "$30.00", "CoGS": "$12.00", "Country": "US"},
            {"Order Code": "100", "Product name": "Hat", "Currency": "",
             "Total": "", "CoGS": "", "Country": ""},
        ]
    )


def test_forward_fill_copies_order_level_onto_child_rows():
    filled = cim.forward_fill_order_level(_two_item_order())
    assert list(filled["Total"]) == ["$30.00", "$30.00"]
    assert list(filled["CoGS"]) == ["$12.00", "$12.00"]
    assert list(filled["Country"]) == ["US", "US"]
    # item-level column is NOT overwritten
    assert list(filled["Product name"]) == ["Tee", "Hat"]


def test_forward_fill_does_not_bleed_across_orders():
    frame = pd.DataFrame(
        [
            {"Order Code": "100", "Product name": "Tee", "Total": "$30.00"},
            {"Order Code": "200", "Product name": "Mug", "Total": ""},
        ]
    )
    filled = cim.forward_fill_order_level(frame)
    # order 200 must NOT inherit order 100's total
    assert list(filled["Total"]) == ["$30.00", ""]


# --- build_raw_rows: multi-item -> single order-grain row ------------------
def test_build_raw_rows_collapses_multi_item_order_to_one_row():
    frame = _two_item_order()
    frame["Project"] = "FOS"
    frame["Status"] = "Completed"
    frame["Date"] = "03/28/2023"
    rows = cim.build_raw_rows(frame, FIXED_TS)

    assert len(rows) == 1
    row = rows[0]
    assert row["site_code"] == "FOS"
    assert row["woo_order_id"] == 100
    assert row["order_total_src"] == 30.0
    assert row["cogs_usd"] == 12.0
    assert row["order_date"] == date(2023, 3, 28)
    assert row["extracted_at"] == FIXED_TS


def test_build_raw_rows_skips_blank_order_code():
    frame = pd.DataFrame(
        [
            {"Project": "FOS", "Order Code": "73874", "Currency": "USD", "CoGS": "$5"},
            {"Project": "FOS", "Order Code": "", "Currency": "USD", "CoGS": "$9"},
            {"Project": "FOS", "Order Code": "Items Information", "Currency": "USD", "CoGS": "$9"},
        ]
    )
    rows = cim.build_raw_rows(frame, FIXED_TS)
    assert [r["woo_order_id"] for r in rows] == [73874]


def test_build_raw_rows_dedupes_repeated_order_code_keeping_first():
    frame = pd.DataFrame(
        [
            {"Project": "FOS", "Order Code": "500", "Total": "$40.00", "Currency": "USD"},
            {"Project": "FOS", "Order Code": "500", "Total": "$40.00", "Currency": "USD"},
        ]
    )
    rows = cim.build_raw_rows(frame, FIXED_TS)
    assert len(rows) == 1
    assert rows[0]["woo_order_id"] == 500


def test_build_raw_rows_classifies_usd_vs_order_currency_columns():
    frame = pd.DataFrame(
        [
            {"Project": "FOS", "Order Code": "600", "Currency": "GBP",
             "Items Subtotal": "£24.82", "Shipping": "£8.09", "Típs/Coupon": "£1.24",
             "Total": "£34.15", "Fee": "£1.80", "Payout": "£32.35",
             "Revenue": "$32.35", "CoGS": "$15.21", "Design fee": "$3.04",
             "Profit": "$14.09", "ROI": "77.21%", "Profit Margin": "43.57%"}
        ]
    )
    row = cim.build_raw_rows(frame, FIXED_TS)[0]

    # order-currency columns land as *_src (FX happens later in dbt)
    assert row["items_subtotal_src"] == 24.82
    assert row["csv_shipping_charged_src"] == 8.09   # customer shipping charge
    assert row["tips_coupon_src"] == 1.24
    assert row["order_total_src"] == 34.15
    assert row["fee_src"] == 1.80                     # -> payment_fee_fallback in dbt
    assert row["payout_src"] == 32.35
    # already-USD columns parse directly, no FX
    assert row["cogs_usd"] == 15.21
    assert row["design_fee_usd"] == 3.04
    assert row["csv_revenue_observed_usd"] == 32.35
    assert row["csv_profit_observed_usd"] == 14.09
    assert row["csv_roi"] == pytest.approx(0.7721)
    assert row["csv_profit_margin"] == pytest.approx(0.4357)


def test_build_raw_rows_payload_excludes_pii_and_keeps_business_fields():
    frame = pd.DataFrame(
        [
            {"Project": "FOS", "Order Code": "700", "Currency": "USD", "CoGS": "$5",
             "Name": "Jane Doe", "Email": "jane@x.com", "Phone": "555", "Ship to": "1 St"},
        ]
    )
    row = cim.build_raw_rows(frame, FIXED_TS)[0]
    payload = row["_payload"]
    assert "Name" not in payload and "Email" not in payload
    assert "Phone" not in payload and "Ship to" not in payload
    assert payload["Order Code"] == "700"
    assert payload["CoGS"] == "$5"


# --- read_csv: sub-header skip ---------------------------------------------
def test_read_csv_skips_two_subheader_rows(tmp_path):
    csv_text = (
        "Date,Status,Project,Order Code,Currency,CoGS\n"
        ",Processing,113,,,\n"                       # sub-header row (skipped)
        ",,,,,\"$63,604.27\"\n"                        # grand-total row (skipped)
        "03/28/2023,Completed,FOS,73874,USD,$14.07\n"  # first real data row
    )
    path = tmp_path / "sample.csv"
    path.write_text(csv_text, encoding="utf-8")

    frame = cim.read_csv(path)
    assert len(frame) == 1
    assert frame.iloc[0]["Order Code"] == "73874"
    assert frame.iloc[0]["Project"] == "FOS"


def test_resolve_csv_path_prefers_env_override():
    override = cim.resolve_csv_path({"CSV_ORDER_MANAGEMENT_PATH": "/tmp/custom.csv"})
    assert str(override).replace("\\", "/") == "/tmp/custom.csv"
    default = cim.resolve_csv_path({})
    assert default == cim.DEFAULT_CSV_PATH
