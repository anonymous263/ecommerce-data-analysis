"""Phase 1 WooCommerce extractor — DB-free unit tests.

Covers the pure payload->row mappers, watermark logic, the idempotent UPSERT
SQL builder, credential resolution, and httpx pagination/backoff using a mock
transport. No Postgres and no network are touched.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest

from src.extract import woo_api
from src.load.upsert import _encode_row, build_upsert_sql, upsert_rows
from src.utils.config import Site
from src.utils.http import MAX_RETRY_AFTER_SECONDS, get_with_retries, paginate

FIXED_TS = datetime(2026, 7, 15, 8, 0, 0, tzinfo=timezone.utc)

SAMPLE_ORDER = {
    "id": 1001,
    "number": "1001",
    "status": "completed",
    "currency": "GBP",
    "date_created_gmt": "2026-07-10T09:00:00",
    "date_modified_gmt": "2026-07-10T12:34:56",
    "line_items": [
        {"id": 5001, "product_id": 42, "quantity": 2},
        {"id": 5002, "product_id": 43, "quantity": 1},
    ],
}


# --- parse_gmt --------------------------------------------------------------
def test_parse_gmt_treats_naive_string_as_utc():
    assert woo_api.parse_gmt("2026-07-10T12:34:56") == datetime(2026, 7, 10, 12, 34, 56, tzinfo=timezone.utc)


def test_parse_gmt_handles_trailing_z_and_blanks():
    assert woo_api.parse_gmt("2026-07-10T12:34:56Z").tzinfo == timezone.utc
    assert woo_api.parse_gmt(None) is None
    assert woo_api.parse_gmt("") is None


# --- mappers ----------------------------------------------------------------
def test_to_order_row_promotes_expected_columns_and_keeps_payload():
    row = woo_api.to_order_row(SAMPLE_ORDER, "FOS", FIXED_TS)
    assert row["site_code"] == "FOS"
    assert row["woo_order_id"] == 1001
    assert row["status"] == "completed"
    assert row["currency"] == "GBP"
    assert row["date_modified_gmt"] == datetime(2026, 7, 10, 12, 34, 56, tzinfo=timezone.utc)
    assert row["extracted_at"] == FIXED_TS
    assert row["_payload"] is SAMPLE_ORDER


def test_order_mapping_is_idempotent():
    # Same input -> byte-identical row dict, which is what makes re-runs safe.
    assert woo_api.to_order_row(SAMPLE_ORDER, "FOS", FIXED_TS) == woo_api.to_order_row(
        SAMPLE_ORDER, "FOS", FIXED_TS
    )


def test_to_order_item_rows_explodes_line_items():
    rows = woo_api.to_order_item_rows(SAMPLE_ORDER, "FOS", FIXED_TS)
    assert [r["woo_order_item_id"] for r in rows] == [5001, 5002]
    assert all(r["woo_order_id"] == 1001 for r in rows)
    assert all(r["site_code"] == "FOS" for r in rows)


def test_to_order_item_rows_handles_missing_line_items():
    assert woo_api.to_order_item_rows({"id": 7}, "FOS", FIXED_TS) == []


def test_to_refund_row_carries_parent_order_id():
    refund = {"id": 9001, "date_created_gmt": "2026-07-11T00:00:00"}
    row = woo_api.to_refund_row(refund, order_id=1001, site_code="FOS", extracted_at=FIXED_TS)
    assert row["woo_refund_id"] == 9001
    assert row["woo_order_id"] == 1001


def test_max_watermark_picks_latest_modified():
    orders = [
        {"date_modified_gmt": "2026-07-10T12:00:00"},
        {"date_modified_gmt": "2026-07-12T06:00:00"},
        {"date_modified_gmt": None},
    ]
    assert woo_api.max_watermark(orders) == datetime(2026, 7, 12, 6, 0, 0, tzinfo=timezone.utc)


def test_max_watermark_empty_is_none():
    assert woo_api.max_watermark([]) is None


# --- upsert SQL -------------------------------------------------------------
def test_build_upsert_sql_is_idempotent_and_excludes_pk():
    sql = build_upsert_sql(
        "raw.woo_orders",
        ["site_code", "woo_order_id", "status", "_payload"],
        ["site_code", "woo_order_id"],
    )
    assert "ON CONFLICT (site_code, woo_order_id)" in sql
    assert "DO UPDATE SET" in sql
    # PK columns must not be reassigned; non-PK columns must be.
    assert "site_code = EXCLUDED.site_code" not in sql
    assert "status = EXCLUDED.status" in sql
    assert "_payload = EXCLUDED._payload" in sql
    # JSONB column is cast from its bound text param.
    assert "CAST(:_payload AS JSONB)" in sql


def test_build_upsert_sql_rejects_unknown_conflict_col():
    with pytest.raises(ValueError):
        build_upsert_sql("raw.woo_orders", ["site_code"], ["woo_order_id"])


# --- credentials ------------------------------------------------------------
def _site() -> Site:
    return Site(
        site_code="FOS",
        site_name="Fashion Open Studio",
        base_url="https://example.test",
        key_env="WOO_FOS_KEY",
        secret_env="WOO_FOS_SECRET",
        default_currency="GBP",
        supported_currencies=("USD", "GBP"),
        timezone="UTC",
        reporting_timezone="Asia/Bangkok",
        is_active=True,
    )


def test_resolve_credentials_reads_named_env_vars():
    creds = woo_api.resolve_credentials(_site(), env={"WOO_FOS_KEY": "ck_x", "WOO_FOS_SECRET": "cs_y"})
    assert (creds.key, creds.secret) == ("ck_x", "cs_y")


def test_resolve_credentials_fails_fast_when_missing():
    with pytest.raises(KeyError):
        woo_api.resolve_credentials(_site(), env={"WOO_FOS_KEY": "ck_x"})


# --- http pagination + backoff ---------------------------------------------
def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), base_url="https://example.test")


def test_paginate_walks_all_pages_and_stops_on_total_pages():
    def handler(request: httpx.Request) -> httpx.Response:
        page = int(dict(request.url.params).get("page", "1"))
        if page == 1:
            return httpx.Response(200, json=[{"id": 1}, {"id": 2}], headers={"X-WP-TotalPages": "2"})
        return httpx.Response(200, json=[{"id": 3}], headers={"X-WP-TotalPages": "2"})

    with _client(handler) as client:
        records = list(paginate(client, "/orders", per_page=2, sleep=lambda _s: None))
    assert [r["id"] for r in records] == [1, 2, 3]


def test_paginate_is_idempotent_across_runs():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"id": 1}], headers={"X-WP-TotalPages": "1"})

    with _client(handler) as client:
        first = list(paginate(client, "/products", per_page=100, sleep=lambda _s: None))
        second = list(paginate(client, "/products", per_page=100, sleep=lambda _s: None))
    assert first == second == [{"id": 1}]


def test_get_with_retries_backs_off_then_succeeds():
    calls = {"n": 0}
    slept: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503)
        return httpx.Response(200, json={"ok": True})

    with _client(handler) as client:
        response = get_with_retries(client, "/orders", sleep=slept.append)
    assert response.status_code == 200
    assert calls["n"] == 3
    assert len(slept) == 2  # two retries before the success


def test_get_with_retries_raises_after_exhausting():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    with _client(handler) as client:
        with pytest.raises(httpx.HTTPStatusError):
            get_with_retries(client, "/orders", sleep=lambda _s: None)


def test_get_with_retries_respects_retry_after_header():
    calls = {"n": 0}
    slept: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "2"}, json=[])
        return httpx.Response(200, json={"ok": True})

    with _client(handler) as client:
        response = get_with_retries(client, "/orders", sleep=slept.append)
    assert response.status_code == 200
    assert slept == [2.0]  # honoured the header, not the exponential default


def test_get_with_retries_clamps_huge_retry_after_to_cap():
    calls = {"n": 0}
    slept: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "99999"}, json=[])
        return httpx.Response(200, json={"ok": True})

    with _client(handler) as client:
        response = get_with_retries(client, "/orders", sleep=slept.append)
    assert response.status_code == 200
    assert slept == [float(MAX_RETRY_AFTER_SECONDS)]


def test_get_with_retries_retries_transient_transport_errors():
    calls = {"n": 0}
    slept: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx.ConnectError("connection reset", request=request)
        return httpx.Response(200, json={"ok": True})

    with _client(handler) as client:
        response = get_with_retries(client, "/orders", sleep=slept.append)
    assert response.status_code == 200
    assert calls["n"] == 3
    assert len(slept) == 2


def test_get_with_retries_raises_transport_error_after_exhausting():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("host down", request=request)

    with _client(handler) as client:
        with pytest.raises(httpx.ConnectError):
            get_with_retries(client, "/orders", sleep=lambda _s: None)


def test_paginate_empty_result_yields_nothing():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    with _client(handler) as client:
        records = list(paginate(client, "/orders", per_page=100, sleep=lambda _s: None))
    assert records == []


def test_paginate_stops_when_short_page_without_total_header():
    def handler(request: httpx.Request) -> httpx.Response:
        page = int(dict(request.url.params).get("page", "1"))
        # First (full) page has no X-WP-TotalPages header; second page is short.
        if page == 1:
            return httpx.Response(200, json=[{"id": 1}, {"id": 2}])
        return httpx.Response(200, json=[{"id": 3}])

    with _client(handler) as client:
        records = list(paginate(client, "/orders", per_page=2, sleep=lambda _s: None))
    assert [r["id"] for r in records] == [1, 2, 3]


# --- extra parse_gmt edge cases --------------------------------------------
def test_parse_gmt_whitespace_only_returns_none():
    assert woo_api.parse_gmt("   ") is None


def test_parse_gmt_handles_offset_and_fractional_seconds():
    assert woo_api.parse_gmt("2026-07-10T12:34:56+00:00") == datetime(
        2026, 7, 10, 12, 34, 56, tzinfo=timezone.utc
    )
    assert woo_api.parse_gmt("2026-07-10T12:34:56.500000") == datetime(
        2026, 7, 10, 12, 34, 56, 500000, tzinfo=timezone.utc
    )


# --- remaining mappers ------------------------------------------------------
def test_to_product_customer_coupon_rows_promote_id_and_keep_payload():
    product = {"id": 42, "date_modified_gmt": "2026-07-10T00:00:00"}
    product_row = woo_api.to_product_row(product, "FOS", FIXED_TS)
    assert product_row["woo_product_id"] == 42
    assert product_row["_payload"] is product
    assert product_row["date_modified_gmt"] == datetime(2026, 7, 10, 0, 0, 0, tzinfo=timezone.utc)

    customer = {"id": 7, "date_modified_gmt": None}
    customer_row = woo_api.to_customer_row(customer, "FOS", FIXED_TS)
    assert customer_row["woo_customer_id"] == 7
    assert customer_row["date_modified_gmt"] is None

    coupon_row = woo_api.to_coupon_row({"id": 3}, "FOS", FIXED_TS)
    assert coupon_row["woo_coupon_id"] == 3
    assert coupon_row["site_code"] == "FOS"


def test_to_order_item_rows_handles_null_line_items():
    assert woo_api.to_order_item_rows({"id": 7, "line_items": None}, "FOS", FIXED_TS) == []


# --- upsert helpers (pure; no DB) ------------------------------------------
def test_build_upsert_sql_do_nothing_when_only_pk_columns():
    sql = build_upsert_sql(
        "raw.woo_refunds",
        ["site_code", "woo_refund_id"],
        ["site_code", "woo_refund_id"],
    )
    assert "DO NOTHING" in sql
    assert "DO UPDATE" not in sql


def test_build_upsert_sql_rejects_empty_conflict_cols():
    with pytest.raises(ValueError):
        build_upsert_sql("raw.woo_orders", ["site_code"], [])


def test_encode_row_serializes_payload_dict_to_json_string():
    encoded = _encode_row({"site_code": "FOS", "_payload": {"a": 1}}, ("_payload",))
    assert encoded["_payload"] == '{"a": 1}'


def test_encode_row_leaves_string_and_none_payload_untouched():
    assert _encode_row({"_payload": '{"already": "json"}'}, ("_payload",))["_payload"] == '{"already": "json"}'
    assert _encode_row({"_payload": None}, ("_payload",))["_payload"] is None


def test_upsert_rows_empty_is_noop_without_touching_engine():
    # engine=None proves no connection is opened for an empty batch.
    assert upsert_rows(None, "raw.woo_orders", [], ["site_code", "woo_order_id"]) == 0


# --- orchestration: watermark advances only on a fully successful pull ------
def _make_fake_paginate(orders, refunds_by_order):
    """A ``paginate`` stand-in that dispatches on the request path."""

    def fake(client, path, params=None, **_kwargs):
        if path == "/orders":
            fake.orders_params = dict(params or {})
            return iter(list(orders))
        order_id = int(path.split("/")[2])  # /orders/<id>/refunds
        return iter(list(refunds_by_order.get(order_id, [])))

    fake.orders_params = {}
    return fake


class _UpsertRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def __call__(self, engine, table, rows, conflict_cols, *args, **kwargs) -> int:
        materialised = list(rows)
        self.calls.append((table, len(materialised)))
        return len(materialised)


class _WatermarkRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, datetime]] = []

    def __call__(self, engine, site_code, entity, watermark) -> None:
        self.calls.append((site_code, entity, watermark))


class _LoadItemsRecorder:
    """Stand-in for ``_load_order_items`` that mirrors its real row count.

    Delegates to the real ``to_order_item_rows`` mapper so the returned count
    matches production behaviour, while recording the order ids it was asked
    to (re)load so tests can assert on them without touching a real engine.
    """

    def __init__(self) -> None:
        self.calls: list[list[int]] = []

    def __call__(self, engine, site_code, orders, extracted_at) -> int:
        order_ids = [int(o["id"]) for o in orders]
        self.calls.append(order_ids)
        item_rows: list[dict] = []
        for order in orders:
            item_rows.extend(woo_api.to_order_item_rows(order, site_code, extracted_at))
        return len(item_rows)


def test_extract_orders_advances_watermark_to_max_modified_on_success(monkeypatch):
    orders = [
        SAMPLE_ORDER,
        {"id": 1002, "date_modified_gmt": "2026-07-14T10:00:00", "line_items": []},
    ]
    refunds = {1001: [{"id": 9001, "date_created_gmt": "2026-07-11T00:00:00"}], 1002: []}
    monkeypatch.setattr(woo_api, "read_watermark", lambda *a, **k: None)
    monkeypatch.setattr(woo_api, "paginate", _make_fake_paginate(orders, refunds))
    upserts = _UpsertRecorder()
    monkeypatch.setattr(woo_api, "upsert_rows", upserts)
    items = _LoadItemsRecorder()
    monkeypatch.setattr(woo_api, "_load_order_items", items)
    watermarks = _WatermarkRecorder()
    monkeypatch.setattr(woo_api, "write_watermark", watermarks)

    total = woo_api._extract_orders_and_refunds(_site(), object(), object(), full_refresh=False)

    # 2 orders + 2 line items (from SAMPLE_ORDER) + 1 refund
    assert total == 5
    assert [table for table, _ in upserts.calls] == [
        "raw.woo_orders",
        "raw.woo_refunds",
    ]
    assert items.calls == [[1001, 1002]]  # order_items load scoped to exactly the pulled orders
    assert len(watermarks.calls) == 1
    assert watermarks.calls[0][2] == datetime(2026, 7, 14, 10, 0, 0, tzinfo=timezone.utc)


def test_extract_orders_sends_gmt_flag_and_modified_after_from_watermark(monkeypatch):
    stored = datetime(2026, 7, 10, 12, 34, 56, tzinfo=timezone.utc)
    monkeypatch.setattr(woo_api, "read_watermark", lambda *a, **k: stored)
    fake = _make_fake_paginate([], {})
    monkeypatch.setattr(woo_api, "paginate", fake)
    monkeypatch.setattr(woo_api, "upsert_rows", lambda *a, **k: 0)
    monkeypatch.setattr(woo_api, "write_watermark", lambda *a, **k: None)

    woo_api._extract_orders_and_refunds(_site(), object(), object(), full_refresh=False)

    assert fake.orders_params["dates_are_gmt"] == "true"
    # modified_after is offset by WATERMARK_OVERLAP (1s) behind the stored watermark.
    assert fake.orders_params["modified_after"] == "2026-07-10T12:34:55"
    assert fake.orders_params["orderby"] == "modified"


def test_extract_orders_modified_after_equals_watermark_minus_overlap_seconds(monkeypatch):
    # FIX 1: modified_after is exclusive, so an order modified in the exact same
    # second as the stored watermark could be skipped forever without an overlap.
    stored = datetime(2026, 7, 10, 12, 34, 56, tzinfo=timezone.utc)
    monkeypatch.setattr(woo_api, "read_watermark", lambda *a, **k: stored)
    fake = _make_fake_paginate([], {})
    monkeypatch.setattr(woo_api, "paginate", fake)
    monkeypatch.setattr(woo_api, "upsert_rows", lambda *a, **k: 0)
    monkeypatch.setattr(woo_api, "write_watermark", lambda *a, **k: None)

    woo_api._extract_orders_and_refunds(_site(), object(), object(), full_refresh=False)

    expected = (stored - woo_api.WATERMARK_OVERLAP).strftime("%Y-%m-%dT%H:%M:%S")
    assert fake.orders_params["modified_after"] == expected == "2026-07-10T12:34:55"


def test_extract_orders_full_refresh_ignores_stored_watermark(monkeypatch):
    monkeypatch.setattr(
        woo_api, "read_watermark", lambda *a, **k: pytest.fail("watermark must not be read on full refresh")
    )
    fake = _make_fake_paginate([], {})
    monkeypatch.setattr(woo_api, "paginate", fake)
    monkeypatch.setattr(woo_api, "upsert_rows", lambda *a, **k: 0)
    monkeypatch.setattr(woo_api, "write_watermark", lambda *a, **k: None)

    woo_api._extract_orders_and_refunds(_site(), object(), object(), full_refresh=True)

    assert "modified_after" not in fake.orders_params


def test_extract_orders_empty_run_does_not_advance_watermark(monkeypatch):
    monkeypatch.setattr(woo_api, "read_watermark", lambda *a, **k: None)
    monkeypatch.setattr(woo_api, "paginate", _make_fake_paginate([], {}))
    monkeypatch.setattr(woo_api, "upsert_rows", lambda *a, **k: 0)
    watermarks = _WatermarkRecorder()
    monkeypatch.setattr(woo_api, "write_watermark", watermarks)

    total = woo_api._extract_orders_and_refunds(_site(), object(), object(), full_refresh=False)

    assert total == 0
    assert watermarks.calls == []


def test_extract_orders_failure_mid_pull_leaves_watermark_unchanged(monkeypatch):
    monkeypatch.setattr(woo_api, "read_watermark", lambda *a, **k: None)
    monkeypatch.setattr(woo_api, "paginate", _make_fake_paginate([SAMPLE_ORDER], {1001: []}))
    monkeypatch.setattr(woo_api, "_load_order_items", lambda *a, **k: 2)

    def failing_upsert(engine, table, rows, conflict_cols, *args, **kwargs) -> int:
        if "refunds" in table:
            raise RuntimeError("database unavailable")
        return len(list(rows))

    monkeypatch.setattr(woo_api, "upsert_rows", failing_upsert)
    watermarks = _WatermarkRecorder()
    monkeypatch.setattr(woo_api, "write_watermark", watermarks)

    with pytest.raises(RuntimeError, match="database unavailable"):
        woo_api._extract_orders_and_refunds(_site(), object(), object(), full_refresh=False)

    assert watermarks.calls == []  # invariant: no advance on partial failure


# --- _load_order_items: authoritative delete-then-insert (FIX 2) -----------
class _FakeConnection:
    """Captures executed (sql_text, params) pairs in call order; no real DB."""

    def __init__(self, statements: list[tuple[str, object]]) -> None:
        self._statements = statements

    def execute(self, sql, params=None):
        self._statements.append((str(sql), params))
        return SimpleNamespace(rowcount=0)


class _FakeEngineCtx:
    def __init__(self, statements: list[tuple[str, object]]) -> None:
        self._statements = statements

    def __enter__(self) -> _FakeConnection:
        return _FakeConnection(self._statements)

    def __exit__(self, *exc) -> bool:
        return False


class _FakeEngine:
    """Records every statement run inside a single ``begin()`` transaction."""

    def __init__(self) -> None:
        self.statements: list[tuple[str, object]] = []

    def begin(self) -> _FakeEngineCtx:
        return _FakeEngineCtx(self.statements)


def test_load_order_items_deletes_before_inserting_for_pulled_order_ids():
    engine = _FakeEngine()
    orders = [SAMPLE_ORDER]  # order 1001 with 2 line items

    total = woo_api._load_order_items(engine, "FOS", orders, FIXED_TS)

    assert total == 2
    assert len(engine.statements) == 2
    delete_sql, delete_params = engine.statements[0]
    insert_sql, insert_params = engine.statements[1]
    assert "DELETE FROM raw.woo_order_items" in delete_sql
    assert "woo_order_id = ANY(:order_ids)" in delete_sql
    assert delete_params == {"site_code": "FOS", "order_ids": [1001]}
    assert "INSERT INTO raw.woo_order_items" in insert_sql
    assert len(insert_params) == 2  # one bound row per line item


def test_load_order_items_re_pull_without_removed_line_item_does_not_retain_orphan():
    # Simulate a re-pull where order 1001 was edited to drop line item 5002:
    # the DELETE must target order 1001 so the orphaned old row is gone before
    # only the remaining current line item (5001) is re-inserted.
    engine = _FakeEngine()
    edited_order = {**SAMPLE_ORDER, "line_items": [{"id": 5001, "product_id": 42, "quantity": 2}]}

    total = woo_api._load_order_items(engine, "FOS", [edited_order], FIXED_TS)

    assert total == 1
    delete_sql, delete_params = engine.statements[0]
    assert "DELETE FROM raw.woo_order_items" in delete_sql
    assert delete_params["order_ids"] == [1001]  # orphaned item 5002's order is in scope
    insert_sql, insert_params = engine.statements[1]
    assert len(insert_params) == 1
    assert insert_params[0]["woo_order_item_id"] == 5001


def test_load_order_items_empty_orders_is_noop_without_touching_engine():
    engine = _FakeEngine()

    total = woo_api._load_order_items(engine, "FOS", [], FIXED_TS)

    assert total == 0
    assert engine.statements == []


def test_load_order_items_order_with_no_line_items_still_deletes_but_skips_insert():
    engine = _FakeEngine()
    order_without_items = {"id": 2002, "line_items": []}

    total = woo_api._load_order_items(engine, "FOS", [order_without_items], FIXED_TS)

    assert total == 0
    assert len(engine.statements) == 1  # DELETE only; no INSERT statement for zero rows
    delete_sql, delete_params = engine.statements[0]
    assert "DELETE FROM raw.woo_order_items" in delete_sql
    assert delete_params["order_ids"] == [2002]


# --- run logging ------------------------------------------------------------
class _DummyClient:
    def __enter__(self):
        return object()

    def __exit__(self, *exc):
        return False


def test_extract_site_logs_successful_run(monkeypatch):
    monkeypatch.setattr(woo_api, "resolve_credentials", lambda site: SimpleNamespace(key="k", secret="s"))
    monkeypatch.setattr(woo_api, "make_client", lambda *a, **k: _DummyClient())
    monkeypatch.setattr(woo_api, "start_run", lambda engine, site_code, start_ts: "run-1")
    monkeypatch.setattr(
        woo_api, "_extract_orders_and_refunds", lambda site, engine, client, *, full_refresh: 5
    )
    monkeypatch.setattr(woo_api, "_extract_simple", lambda site, engine, client, entity, mapper: 1)
    finished: dict = {}

    def fake_finish(engine, run_id, *, status, rows_out, end_ts, error_text=None):
        finished.update(run_id=run_id, status=status, rows_out=rows_out, error_text=error_text)

    monkeypatch.setattr(woo_api, "finish_run", fake_finish)

    total = woo_api.extract_site(_site(), object(), full_refresh=False)

    assert total == 8  # 5 orders/items/refunds + 3 simple entities * 1
    assert finished["status"] == "success"
    assert finished["rows_out"] == 8
    assert finished["error_text"] is None


def test_extract_site_logs_failed_run_and_reraises(monkeypatch):
    monkeypatch.setattr(woo_api, "resolve_credentials", lambda site: SimpleNamespace(key="k", secret="s"))
    monkeypatch.setattr(woo_api, "make_client", lambda *a, **k: _DummyClient())
    monkeypatch.setattr(woo_api, "start_run", lambda *a, **k: "run-1")

    def boom(*args, **kwargs):
        raise RuntimeError("api 500")

    monkeypatch.setattr(woo_api, "_extract_orders_and_refunds", boom)
    finished: dict = {}

    def fake_finish(engine, run_id, *, status, rows_out, end_ts, error_text=None):
        finished.update(status=status, rows_out=rows_out, error_text=error_text)

    monkeypatch.setattr(woo_api, "finish_run", fake_finish)

    with pytest.raises(RuntimeError, match="api 500"):
        woo_api.extract_site(_site(), object(), full_refresh=False)

    assert finished["status"] == "failed"
    assert "api 500" in finished["error_text"]
