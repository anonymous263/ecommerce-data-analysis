import csv
from pathlib import Path

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_sites_yaml():
    return yaml.safe_load((PROJECT_ROOT / "config/sites.yaml").read_text(encoding="utf-8"))["sites"]


def _load_site_seed():
    with (PROJECT_ROOT / "dbt/seeds/dim_site_seed.csv").open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_sites_yaml_and_seed_have_same_site_codes():
    yaml_site_codes = {site["site_code"] for site in _load_sites_yaml()}
    seed_site_codes = {site["site_code"] for site in _load_site_seed()}

    assert yaml_site_codes == seed_site_codes == {"FOS"}


def test_fos_site_metadata_matches_between_yaml_and_seed():
    yaml_site = {site["site_code"]: site for site in _load_sites_yaml()}["FOS"]
    seed_site = {site["site_code"]: site for site in _load_site_seed()}["FOS"]

    assert seed_site["site_name"] == yaml_site["site_name"] == "Fashion Open Studio"
    assert yaml_site["supported_currencies"] == ["USD", "GBP", "CAD", "EUR"]
    assert seed_site["timezone"] == yaml_site["timezone"] == "UTC"
    assert seed_site["reporting_timezone"] == yaml_site["reporting_timezone"] == "Asia/Bangkok"
    assert seed_site["is_active"].lower() == str(yaml_site["is_active"]).lower()


# --- privacy guards ---------------------------------------------------------
# This repo is public. Storefront URLs are private infrastructure and must stay
# in .env, reachable only through the `base_url_env` name indirection — the same
# rule the consumer key/secret already follow.
def test_sites_yaml_declares_base_url_by_env_name_only():
    for site in _load_sites_yaml():
        assert "base_url" not in site, f"{site['site_code']}: literal base_url must not be committed"
        assert site["base_url_env"].endswith("_BASE_URL")


def test_no_live_storefront_url_in_committed_site_config():
    raw_yaml = (PROJECT_ROOT / "config/sites.yaml").read_text(encoding="utf-8")

    assert "http://" not in raw_yaml
    assert "https://" not in raw_yaml


def test_site_seed_domain_column_is_blank():
    for site in _load_site_seed():
        assert site["domain"] == "", f"{site['site_code']}: domain must stay blank in the committed seed"
