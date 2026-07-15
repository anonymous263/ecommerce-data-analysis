"""Postgres connection factory for the EL pipelines.

Builds a SQLAlchemy engine from the ``POSTGRES_*`` environment variables
(loaded from ``.env`` — see docs/PIPELINE_DESIGN.md §11) and provides a small
helper to apply a DDL script such as ``sql/ddl/01_raw_woo.sql``.
"""
from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import Engine, create_engine

from src.utils.logging import get_logger

logger = get_logger(__name__)

_DEFAULTS = {
    "POSTGRES_HOST": "localhost",
    "POSTGRES_PORT": "5432",
    "POSTGRES_DB": "ecommerce",
    "POSTGRES_USER": "ecommerce",
}


def _env(name: str, env: dict[str, str]) -> str:
    return env.get(name, _DEFAULTS.get(name, "")).strip()


def make_engine(env: dict[str, str] | None = None) -> Engine:
    """Create a SQLAlchemy engine for the analytics Postgres.

    Password is required (no default) so a run fails fast rather than attempting
    an anonymous connection.
    """
    source = dict(env) if env is not None else dict(os.environ)
    password = source.get("POSTGRES_PASSWORD", "").strip()
    if not password:
        raise KeyError("POSTGRES_PASSWORD is not set")

    url = (
        f"postgresql+psycopg2://{_env('POSTGRES_USER', source)}:{password}"
        f"@{_env('POSTGRES_HOST', source)}:{_env('POSTGRES_PORT', source)}"
        f"/{_env('POSTGRES_DB', source)}"
    )
    logger.debug("Creating engine for %s@%s", _env("POSTGRES_USER", source), _env("POSTGRES_HOST", source))
    return create_engine(url, future=True)


def apply_sql_file(engine: Engine, sql_path: Path) -> None:
    """Execute a ``.sql`` script (e.g. the raw-schema DDL) against the database.

    Uses ``exec_driver_sql`` so the multi-statement script is sent verbatim to
    psycopg2 without SQLAlchemy attempting to parse ``:name`` bind params.
    """
    script = sql_path.read_text(encoding="utf-8")
    with engine.begin() as conn:
        conn.exec_driver_sql(script)
    logger.info("Applied SQL file %s", sql_path.name)
