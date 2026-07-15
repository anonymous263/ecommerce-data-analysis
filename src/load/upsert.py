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

from psycopg2.extras import execute_values
from sqlalchemy import Engine, text

from src.utils.logging import get_logger

logger = get_logger(__name__)

DEFAULT_JSON_COLUMNS = ("_payload",)
BULK_PAGE_SIZE = 1000  # rows per multi-VALUES statement in execute_values


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


def build_bulk_upsert_sql(
    table: str,
    columns: Sequence[str],
    conflict_cols: Sequence[str],
    json_columns: Sequence[str] = DEFAULT_JSON_COLUMNS,
) -> tuple[str, str]:
    """Return ``(sql, template)`` for a batched ``execute_values`` UPSERT.

    ``sql`` carries the single ``VALUES %s`` placeholder execute_values expands;
    ``template`` renders one row, casting ``json_columns`` to JSONB. Conflict/PK
    columns are excluded from the UPDATE set (idempotent re-run).
    """
    if not conflict_cols:
        raise ValueError("conflict_cols must be non-empty for an idempotent upsert")
    unknown = [c for c in conflict_cols if c not in columns]
    if unknown:
        raise ValueError(f"conflict_cols not in columns: {unknown}")

    json_set = set(json_columns)
    conflict_set = set(conflict_cols)
    insert_cols = ", ".join(columns)
    conflict = ", ".join(conflict_cols)
    update_cols = [c for c in columns if c not in conflict_set]
    assignments = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)
    action = f"DO UPDATE SET {assignments}" if assignments else "DO NOTHING"

    sql = f"INSERT INTO {table} ({insert_cols}) VALUES %s ON CONFLICT ({conflict}) {action}"
    template = "(" + ", ".join(
        "CAST(%s AS JSONB)" if c in json_set else "%s" for c in columns
    ) + ")"
    return sql, template


def upsert_rows(
    engine: Engine,
    table: str,
    rows: Sequence[Mapping[str, Any]],
    conflict_cols: Sequence[str],
    json_columns: Sequence[str] = DEFAULT_JSON_COLUMNS,
    *,
    truncate_first: bool = False,
) -> int:
    """UPSERT ``rows`` into ``table`` via batched ``execute_values``; returns the
    number of rows submitted.

    Column list is taken from the first row (all rows must share keys). A no-op
    when ``rows`` is empty and ``truncate_first`` is False. Batched at
    ``BULK_PAGE_SIZE`` so a 58k-row load is a handful of multi-VALUES
    statements, not one round trip per row.

    ``truncate_first=True`` runs ``TRUNCATE TABLE`` in the SAME transaction as
    the insert (snapshot-reload sources such as the manual CSV pipeline), so a
    mid-load failure rolls back to the prior good snapshot instead of leaving
    the table empty — a TRUNCATE committed in its own transaction followed by a
    separately-failed insert would otherwise lose the whole table.
    """
    if not rows:
        if truncate_first:
            with engine.begin() as conn:
                conn.exec_driver_sql(f"TRUNCATE TABLE {table}")
            logger.info("Truncated %s (no rows to reload)", table)
        return 0
    columns = list(rows[0].keys())
    json_set = set(json_columns)
    sql, template = build_bulk_upsert_sql(table, columns, conflict_cols, json_columns)

    def to_tuple(row: Mapping[str, Any]) -> tuple[Any, ...]:
        values: list[Any] = []
        for col in columns:
            value = row.get(col)
            if col in json_set and not isinstance(value, (str, type(None))):
                value = json.dumps(value, ensure_ascii=False, default=str)
            values.append(value)
        return tuple(values)

    argslist = [to_tuple(row) for row in rows]
    with engine.begin() as conn:
        if truncate_first:
            conn.exec_driver_sql(f"TRUNCATE TABLE {table}")
        cursor = conn.connection.cursor()
        try:
            execute_values(cursor, sql, argslist, template=template, page_size=BULK_PAGE_SIZE)
        finally:
            cursor.close()
    logger.info(
        "%s %d rows into %s",
        "Truncated and reloaded" if truncate_first else "Upserted",
        len(argslist),
        table,
    )
    return len(argslist)
