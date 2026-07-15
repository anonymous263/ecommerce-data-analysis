"""HTTP helpers for WooCommerce REST pulls.

httpx client with exponential backoff on 429/5xx and transient transport errors
(max 5 retries, §9.2) plus a generator that walks WooCommerce's page-based
pagination. No business logic — this returns decoded JSON exactly as the API
sends it.
"""
from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

import httpx

from src.utils.logging import get_logger

logger = get_logger(__name__)

MAX_RETRIES = 5
BACKOFF_BASE_SECONDS = 1.0
# 429/5xx plus Cloudflare-specific 520-524 (origin/edge hiccups fronting the store).
RETRY_STATUS = frozenset({429, 500, 502, 503, 504, 520, 521, 522, 523, 524})
DEFAULT_TIMEOUT = 30.0
DEFAULT_PER_PAGE = 100
MAX_RETRY_AFTER_SECONDS = 60  # cap a hostile/huge Retry-After so a run can't stall for hours
# Cloudflare's WAF rejects the bare python-httpx UA with a 520; a real UA is required.
DEFAULT_USER_AGENT = "EcommerceWarehouse/1.0 (Phase 1 EL; +https://github.com/anonymous263)"


def backoff_seconds(attempt: int, base: float = BACKOFF_BASE_SECONDS) -> float:
    """Exponential backoff delay for a 0-indexed retry ``attempt`` (1s, 2s, 4s, ...)."""
    return base * (2 ** attempt)


def make_client(base_url: str, key: str, secret: str, timeout: float = DEFAULT_TIMEOUT) -> httpx.Client:
    """Build an httpx client bound to a site's WooCommerce API with Basic auth."""
    return httpx.Client(
        base_url=base_url.rstrip("/") + "/wp-json/wc/v3",
        auth=(key, secret),
        timeout=timeout,
        headers={"Accept": "application/json", "User-Agent": DEFAULT_USER_AGENT},
    )


def get_with_retries(
    client: httpx.Client,
    path: str,
    params: dict[str, Any] | None = None,
    *,
    sleep=time.sleep,
) -> httpx.Response:
    """GET ``path`` with exponential backoff on transient errors.

    ``sleep`` is injectable so tests can run without real delays. Raises the
    final ``httpx.HTTPStatusError`` if every retry is exhausted.
    """
    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            response = client.get(path, params=params)
        except httpx.TransportError as exc:
            # Connection reset, read timeout, DNS blip, etc. — transient; retry.
            last_exc = exc
            if attempt >= MAX_RETRIES - 1:
                raise
            delay = backoff_seconds(attempt)
            logger.warning(
                "GET %s raised %s; retry %d/%d in %.1fs",
                path, type(exc).__name__, attempt + 1, MAX_RETRIES - 1, delay,
            )
            sleep(delay)
            continue

        if response.status_code not in RETRY_STATUS:
            response.raise_for_status()
            return response

        last_exc = httpx.HTTPStatusError(
            f"{response.status_code} from {path}", request=response.request, response=response
        )
        if attempt < MAX_RETRIES - 1:
            delay = _retry_after(response) or backoff_seconds(attempt)
            logger.warning(
                "GET %s -> %s; retry %d/%d in %.1fs",
                path, response.status_code, attempt + 1, MAX_RETRIES - 1, delay,
            )
            sleep(delay)

    assert last_exc is not None
    raise last_exc


def paginate(
    client: httpx.Client,
    path: str,
    params: dict[str, Any] | None = None,
    *,
    per_page: int = DEFAULT_PER_PAGE,
    sleep=time.sleep,
) -> Iterator[dict[str, Any]]:
    """Yield every record across all pages of a WooCommerce list endpoint.

    Stops when a page returns fewer than ``per_page`` records or when the
    ``X-WP-TotalPages`` header says the last page was reached.
    """
    base_params = dict(params or {})
    base_params["per_page"] = per_page
    page = 1
    while True:
        page_params = {**base_params, "page": page}
        response = get_with_retries(client, path, page_params, sleep=sleep)
        records = response.json()
        if not isinstance(records, list):
            raise TypeError(f"Expected a JSON list from {path}, got {type(records).__name__}")

        yield from records

        total_pages = _int_header(response, "X-WP-TotalPages")
        if len(records) < per_page or (total_pages is not None and page >= total_pages):
            return
        page += 1


def _retry_after(response: httpx.Response) -> float | None:
    raw = response.headers.get("Retry-After")
    if raw is None:
        return None
    try:
        parsed = float(raw)
    except ValueError:
        return None
    return min(parsed, MAX_RETRY_AFTER_SECONDS)


def _int_header(response: httpx.Response, name: str) -> int | None:
    raw = response.headers.get(name)
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None
