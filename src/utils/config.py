"""Site configuration + credential resolution.

Reads ``config/sites.yaml`` (the canonical multi-site list) and resolves each
site's WooCommerce base URL and consumer key/secret from the environment via the
*env-var name* indirection stored in the yaml (``base_url_env`` / ``key_env`` /
``secret_env``). Neither secrets nor storefront endpoints live in the yaml — only
the names of the env vars that hold them, so the committed config discloses no
private infrastructure.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SITES_CONFIG_PATH = PROJECT_ROOT / "config" / "sites.yaml"


@dataclass(frozen=True)
class Site:
    """One store from config/sites.yaml (metadata only — no secrets)."""

    site_code: str
    site_name: str
    base_url_env: str
    key_env: str
    secret_env: str
    default_currency: str
    supported_currencies: tuple[str, ...]
    timezone: str
    reporting_timezone: str
    is_active: bool


@dataclass(frozen=True)
class Credentials:
    key: str
    secret: str


def load_sites(config_path: Path = SITES_CONFIG_PATH, *, active_only: bool = False) -> list[Site]:
    """Load and validate the site list from ``config_path``."""
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    sites = [
        Site(
            site_code=entry["site_code"],
            site_name=entry["site_name"],
            base_url_env=entry["base_url_env"],
            key_env=entry["key_env"],
            secret_env=entry["secret_env"],
            default_currency=entry["default_currency"],
            supported_currencies=tuple(entry["supported_currencies"]),
            timezone=entry["timezone"],
            reporting_timezone=entry["reporting_timezone"],
            is_active=bool(entry["is_active"]),
        )
        for entry in raw["sites"]
    ]
    if active_only:
        return [site for site in sites if site.is_active]
    return sites


def resolve_base_url(site: Site, env: dict[str, str] | None = None) -> str:
    """Resolve a site's storefront base URL from the environment.

    The real domain is deliberately kept out of the committed config (same
    indirection as the credentials), so a public checkout of this repo exposes
    no live storefront endpoint. Raises ``KeyError`` (fail-fast) when the env var
    is unset or blank rather than falling back to a guessable default.
    """
    source = env if env is not None else os.environ
    base_url = source.get(site.base_url_env, "").strip()
    if not base_url:
        raise KeyError(f"Missing WooCommerce base URL for site {site.site_code}: {site.base_url_env}")
    return base_url


def resolve_credentials(site: Site, env: dict[str, str] | None = None) -> Credentials:
    """Resolve a site's WooCommerce key/secret from the environment.

    Raises ``KeyError`` (fail-fast) when either env var is unset or blank so a
    misconfigured run never silently pulls with empty auth.
    """
    source = env if env is not None else os.environ
    key = source.get(site.key_env, "").strip()
    secret = source.get(site.secret_env, "").strip()
    missing = [name for name, value in ((site.key_env, key), (site.secret_env, secret)) if not value]
    if missing:
        raise KeyError(f"Missing WooCommerce credentials for site {site.site_code}: {', '.join(missing)}")
    return Credentials(key=key, secret=secret)
