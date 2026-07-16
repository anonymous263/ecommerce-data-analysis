# Moving the database to another machine

You want to clone the repo on your home machine and keep developing with the same
warehouse. Here's the honest situation and the three ways to do it.

## Why the dump is **not** pushed with the repo

- **Size:** the full DB is **612 MB**; the compressed dump (`db/dumps/ecommerce_full.dump`)
  is **~205 MB**. GitHub's hard limit is **100 MB per file** — a normal `git push` is
  rejected outright. You'd need Git LFS.
- **PII:** `raw.woo_orders` / `raw.woo_products` payloads (`_payload` JSONB) still contain
  **real customer names, emails, and addresses** — the hashing only happens later, in dbt
  staging. Anything committed to git lives in history **forever**; before this repo ever
  goes public you would have to rewrite history to purge it (painful).

For those reasons `db/dumps/` and `*.dump` are **gitignored**. The dump file exists locally,
ready for whichever option you pick below.

---

## Option A — Rebuild from source (recommended, cleanest)

The whole 612 MB warehouse is reproducible from source, so nothing large or sensitive
touches git. On the home machine, after cloning:

```powershell
docker compose up -d postgres          # empty Postgres 16
# copy .env and the manual CSV over out-of-band first (see "What to move by hand")
python -m src.extract.woo_api           # re-pull orders/products from the Woo API
python -m src.extract.csv_order_management
cd dbt && dbt build                     # rebuild staging + marts
```

This is exactly the refresh runbook in `docs/PIPELINE_DESIGN.md §5.7`. Needs Woo API access
(keys in `.env`) and the manual CSV — both moved by hand, both small.

## Option B — Move the dump out-of-band (exact current state)

Keeps the precise current DB (including any manual tweaks) without git. Copy the dump via a
private channel (cloud drive, USB, `scp`) and restore:

```powershell
docker compose up -d postgres
# then, from the repo root on the home machine:
docker exec -i ecommerce_postgres pg_restore -U ecommerce -d ecommerce --clean --if-exists < db/dumps/ecommerce_full.dump
```

## Option C — Git LFS (only if you insist on git)

Real PII still ends up in history. If you accept that (private repo, will scrub before public):

```powershell
git lfs install
git lfs track "db/dumps/*.dump"
# remove the db/dumps ignore line, then add + commit the .gitattributes and the dump
```

---

## What to move by hand regardless (never via git)

- **`.env`** — holds `POSTGRES_*`, `WOO_FOS_KEY/_SECRET`, and **`PII_SALT`**.
  `PII_SALT` is critical: it's the salt behind every `customer_hash`. If it differs on the
  home machine, customer linkage breaks and hashes won't match the current warehouse. Copy
  the same `.env` over — do **not** regenerate the salt.
- **The manual CSV** (`data/raw/manual/order_management.csv`) — gitignored, needed for Option A.

## Regenerating the dump

```powershell
docker exec ecommerce_postgres pg_dump -U ecommerce -Fc ecommerce > db/dumps/ecommerce_full.dump
```
