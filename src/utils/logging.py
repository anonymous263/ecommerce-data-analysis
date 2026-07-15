"""Structured logging helper for the EL pipelines.

Thin wrapper over the stdlib ``logging`` module so extract/load code never
reaches for ``print``. One configured logger per module; repeated calls with
the same name return the same handler set (no duplicate lines).
"""
from __future__ import annotations

import logging
import os
import sys

_CONFIGURED: set[str] = set()

_DEFAULT_FORMAT = "%(asctime)s %(levelname)-7s %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S%z"


def get_logger(name: str) -> logging.Logger:
    """Return a logger writing to stderr at the ``LOG_LEVEL`` env level (default INFO)."""
    logger = logging.getLogger(name)
    if name in _CONFIGURED:
        return logger

    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    logger.setLevel(getattr(logging, level_name, logging.INFO))

    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(logging.Formatter(fmt=_DEFAULT_FORMAT, datefmt=_DATE_FORMAT))
    logger.addHandler(handler)
    logger.propagate = False

    _CONFIGURED.add(name)
    return logger
