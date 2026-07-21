from pathlib import Path

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_phase0_required_files_exist():
    required_files = [
        ".gitignore",
        ".env.example",
        "requirements.txt",
        "docker-compose.yml",
        "config/sites.yaml",
        "sql/init/01_create_schemas.sql",
        "dbt/dbt_project.yml",
        "dbt/packages.yml",
        "dbt/profiles.yml.example",
        "dbt/seeds/dim_site_seed.csv",
        "dbt/seeds/dim_supplier_seed.csv",
        "dbt/seeds/country_iso_map.csv",
        "dbt/seeds/fx_rates.csv",
        "dbt/seeds/payment_fees.csv",
    ]

    missing = [path for path in required_files if not (PROJECT_ROOT / path).is_file()]

    assert missing == []


def test_phase0_required_directories_exist():
    required_dirs = [
        "src/extract",
        "src/load",
        "src/utils",
        "tests",
        "dbt/models/staging/woocommerce",
        "dbt/models/staging/manual",
        "dbt/models/staging/ga4",
        "dbt/models/marts/core",
        "dbt/models/marts/operations",
        "dbt/models/marts/marketing",
        "dbt/models/marts/reconciliation",
        "dbt/macros",
        "dbt/tests/singular",
        "dbt/seeds",
    ]

    missing = [path for path in required_dirs if not (PROJECT_ROOT / path).is_dir()]

    assert missing == []


def test_gitignore_protects_private_and_generated_files():
    gitignore = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
    required_patterns = [
        ".env",
        ".env.*",
        "!.env.example",
        "data/raw/",
        "Order Management.csv",
        "POD Management - Order*.csv",
        "dbt/target/",
        "dbt/dbt_packages/",
        "__pycache__/",
        ".venv/",
        "*.pbix.backup",
        "*service-account*.json",
    ]

    missing = [pattern for pattern in required_patterns if pattern not in gitignore]

    assert missing == []


def test_env_example_contains_only_placeholders():
    env_example = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
    required_names = [
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "POSTGRES_DB",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "PII_SALT",
        "WOO_FOS_KEY",
        "WOO_FOS_SECRET",
        "GOOGLE_APPLICATION_CREDENTIALS",
    ]

    missing = [name for name in required_names if f"{name}=" not in env_example]

    assert missing == []
    assert "placeholder" in env_example.lower()


def test_docker_compose_uses_postgres_16_and_safe_env_defaults():
    compose = yaml.safe_load((PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    postgres = compose["services"]["postgres"]
    environment = postgres["environment"]

    assert postgres["image"].startswith("postgres:16")
    assert environment["POSTGRES_PASSWORD"] == "${POSTGRES_PASSWORD:-postgres}"
    assert "${POSTGRES_PORT:-5432}:5432" in postgres["ports"]


def test_schema_init_creates_required_postgres_schemas():
    ddl = (PROJECT_ROOT / "sql/init/01_create_schemas.sql").read_text(encoding="utf-8")
    required_schemas = [
        "raw",
        "staging",
        "marts_core",
        "marts_marketing",
        "marts_operations",
        "marts_recon",
    ]

    missing = [
        schema
        for schema in required_schemas
        if f"CREATE SCHEMA IF NOT EXISTS {schema};" not in ddl
    ]

    assert missing == []


def test_dbt_project_declares_expected_packages_and_schemas():
    dbt_project = yaml.safe_load((PROJECT_ROOT / "dbt/dbt_project.yml").read_text(encoding="utf-8"))
    packages = yaml.safe_load((PROJECT_ROOT / "dbt/packages.yml").read_text(encoding="utf-8"))
    package_names = {package["package"] for package in packages["packages"]}

    assert dbt_project["name"] == "ecommerce_analytics"
    assert dbt_project["profile"] == "ecommerce_analytics"
    assert package_names == {"dbt-labs/dbt_utils", "calogica/dbt_expectations"}


COMMENT_PREFIXES = ("--", "#", "//", "///", "/*", "*")


def _strip_comment_lines(text: str) -> str:
    """Drop whole-line comments so prose *documenting* a banned identifier does not
    read as a *use* of it.

    The rule this guards is that `actual_shipping_cost_usd` must not exist as a real
    field in any model or DAX measure. The docs and the DAX library deliberately name
    it in comments to warn that it does not exist (see CLAUDE.md rule #3), which a
    bare substring scan would flag as the very violation it is warning about.
    """
    kept = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(COMMENT_PREFIXES):
            continue
        kept.append(line)
    return "\n".join(kept)


def test_no_forbidden_shipping_cost_field_in_implementation_scaffold():
    scanned_roots = ["dbt", "sql", "src", "powerbi"]
    offenders = []
    for root_name in scanned_roots:
        root = PROJECT_ROOT / root_name
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file() and path.suffix.lower() in {".sql", ".yml", ".yaml", ".csv", ".py", ".txt"}:
                text = _strip_comment_lines(path.read_text(encoding="utf-8", errors="ignore"))
                if "actual_shipping_cost_usd" in text:
                    offenders.append(str(path.relative_to(PROJECT_ROOT)))

    assert offenders == []
