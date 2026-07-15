"""Idempotent UPSERT into the raw landing tables.

Builds and executes ``INSERT ... ON CONFLICT (<pk>) DO UPDATE`` so re-running
an extract over the same window updates rows in place — never duplicates
(docs/PIPELINE_DESIGN.md §3). The conflict/PK columns are excluded from the
UPDATE set; JSONB columns are cast explicitly from their bound text param.
"""
from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import Engine, text

from src.utils.logging import get_logger

logger = get_logger(__name__)

DEFAULT_JSON_COLUMNS = ("_payload",)


def build_upsert_sql(
    table: str,
    columns: Sequence[str],
    conflict_cols: Sequence[str],
    json_columns: Sequence[str] = DEFAULT_JSON_COLUMNS,
) -> str:
    """Return a parameterised UPSERT statement for ``table``.

    ``columns`` is the full ordered column list. ``conflict_cols`` form the PK
    and are never updated. ``json_columns`` are wrapped in ``CAST(... AS JSONB)``.
    """
    if not conflict_cols:
        raise ValueError("conflict_cols must be non-empty for an idempotent upsert")
    unknown = [c for c in conflict_cols if c not in columns]
    if unknown:
        raise ValueError(f"conflict_cols not in columns: {unknown}")

    json_set = set(json_columns)

    def placeholder(col: str) -> str:
        return f"CAST(:{col} AS JSONB)" if col in json_set else f":{col}"

    insert_cols = ", ".join(columns)
    values = ", ".join(placeholder(col) for col in columns)
    conflict = ", ".join(conflict_cols)

    update_cols = [col for col in columns if col not in set(conflict_cols)]
    assignments = ", ".join(f"{col} = EXCLUDED.{col}" for col in update_cols)

    action = f"DO UPDATE SET {assignments}" if assignments else "DO NOTHING"
    return (
        f"INSERT INTO {table} ({insert_cols})\n"
        f"VALUES ({values})\n"
        f"ON CONFLICT ({conflict}) {action}"
    )


def _encode_row(row: Mapping[str, Any], json_columns: Sequence[str]) -> dict[str, Any]:
    encoded = dict(row)
    for col in json_columns:
        if col in encoded and not isinstance(encoded[col], (str, type(None))):
            encoded[col] = json.dumps(encoded[col], ensure_ascii=False, default=str)
    return encoded


def upsert_rows(
    engine: Engine,
    table: str,
    rows: Sequence[Mapping[str, Any]],
    conflict_cols: Sequence[str],
    json_columns: Sequence[str] = DEFAULT_JSON_COLUMNS,
) -> int:
    """UPSERT ``rows`` into ``table``; returns the number of rows submitted.

    Column list is taken from the first row (all rows must share keys). A no-op
    when ``rows`` is empty.
    """
    if not rows:
        return 0
    columns = list(rows[0].keys())
    sql = build_upsert_sql(table, columns, conflict_cols, json_columns)
    params = [_encode_row(row, json_columns) for row in rows]
    with engine.begin() as conn:
        conn.execute(text(sql), params)
    logger.info("Upserted %d rows into %s", len(params), table)
    return len(params)
