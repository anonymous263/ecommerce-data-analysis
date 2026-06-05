import csv
from pathlib import Path
from urllib.parse import urlparse

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
    yaml_domain = urlparse(yaml_site["base_url"]).netloc

    assert seed_site["site_name"] == yaml_site["site_name"] == "Fashion Open Studio"
    assert seed_site["domain"] == yaml_domain == "fashionopenstudio.com"
    assert yaml_site["supported_currencies"] == ["USD", "GBP", "CAD", "EUR"]
    assert seed_site["timezone"] == yaml_site["timezone"] == "UTC"
    assert seed_site["reporting_timezone"] == yaml_site["reporting_timezone"] == "Asia/Bangkok"
    assert seed_site["is_active"].lower() == str(yaml_site["is_active"]).lower()
