# AGENTS.md

Guidance for Codex, Claude Code, and any other coding agent working in this repository. Codex is the main implementation agent; this file is written to be useful to any agent. Read it before making changes.

The source of truth for *what to build* is the docs (see reading order). This file tells you *how to behave* while building it. **If anything here conflicts with the docs, the precedence order is: `CLAUDE.md`, `TASKS.md`, `docs/DATA_MODEL.md`, `docs/PIPELINE_DESIGN.md`, `docs/METRICS_DEFINITION.md`, `docs/ROADMAP.md` win — then this file, then the remaining docs.**

---

## 1. Project summary

A **private business warehouse first, portfolio second** — an analytics warehouse for several WooCommerce print-on-demand (POD) apparel stores fulfilled by external suppliers.

Source-of-truth mapping (do not violate):

| Domain | System of record |
|---|---|
| Orders, order items, products, customers, refunds, order status, **customer shipping charge** | **WooCommerce REST API** |
| **COGS** (incl. supplier fulfillment/shipping fee), design fee, supplier, tracking, fulfillment enrichment | **Manual `Order Management.csv`** (Google Sheet export) |
| Behavior, funnel, landing pages | **GA4 BigQuery export** |
| Ad spend / ROAS / CAC | **Optional future only** — no ads running, not part of MVP |

Pipeline shape: `Sources → Python extract/load (EL only) → Postgres raw → dbt (raw→staging→marts) → Power BI`. Python lands raw data only; **all business logic lives in dbt.**

---

## 2. Current status

- **Planning / Phase 0.** The repo is documentation plus an empty directory skeleton (`.gitkeep` placeholders).
- **No production pipeline code exists yet.**
- **No dbt project is fully implemented yet.**
- **No Postgres environment is assumed to be running.**
- Agents must **build from the specs in `docs/`, not invent their own architecture.** Do not change the existing architecture unless you find a genuine contradiction between the precedence docs — in which case stop and surface it rather than silently choosing.

---

## 3. Required reading order

Read these before implementing anything:

1. `README.md`
2. `AGENTS.md` (this file)
3. `TASKS.md`
4. `CLAUDE.md`
5. `docs/PROJECT_PLAN.md`
6. `docs/DATA_AUDIT.md`
7. `docs/DATA_MODEL.md`
8. `docs/PIPELINE_DESIGN.md`
9. `docs/METRICS_DEFINITION.md`
10. `docs/DASHBOARD_SPEC.md`
11. `docs/ROADMAP.md`
12. Then the **phase-specific audit docs** for the phase you are on: `docs/WOO_PAYLOAD_AUDIT.md` (Phase 1), `docs/GA4_BIGQUERY_AUDIT.md` (Phase 6).

---

## 4. Non-negotiable domain rules

These are load-bearing invariants. Violating them silently corrupts every metric. Preserve them in Python, SQL/dbt, and DAX:

1. **Revenue lives once, at `fact_order_item.line_revenue_usd`.** Roll up from line items.
2. **`fact_order` must NOT contain a `revenue_usd` column** (prevents the order × item double-count).
3. **Contribution profit = `revenue_usd − cogs_usd − design_fee_usd − payment_fee_usd`.**
4. **Do not subtract shipping cost separately.**
5. **COGS already includes the supplier fulfillment/shipping fee where applicable** (that's why there's no separate shipping term).
6. **The CSV `Shipping` column means shipping charged to the *customer* (revenue-side), not supplier shipping cost.** It is loaded for reconciliation only (`recon_woo_vs_csv_shipping_charged`). The official customer shipping charge is Woo's `fact_order.shipping_charged_usd`.
7. **CSV `Revenue` / `Profit` / `ROI` / `Profit Margin` are never official metrics** — reconciliation only, in `marts_recon.recon_csv_vs_dbt_*`.
8. **There must be no `actual_shipping_cost_usd` field anywhere** — not in models, DDL, dbt, or DAX. If you see one, it is a bug. (If a future supplier API ever exposes supplier shipping as a separate number, `cogs_usd` and the profit formula must be reworked together — see `docs/DATA_MODEL.md §4.1`. Until then, do not model it.)

---

## 5. Privacy rules

- **`.env` is gitignored.** Secrets live there only: `POSTGRES_*`, `WOO_<SITECODE>_KEY`/`_SECRET`, `PII_SALT`, `GOOGLE_APPLICATION_CREDENTIALS`. `.env.example` (placeholders only) is committed.
- **`Order Management.csv` is gitignored.**
- **`data/raw/` is gitignored.**
- **Real Woo extracts are private-only** — local disk only, never exported, never in the public sample.
- **Manual CSV PII columns `Name`, `Email`, `Phone`, `Ship to` must be dropped BEFORE loading `raw.csv_order_management`.** Therefore raw is not a byte-for-byte copy of the sheet. Tracking IDs / fulfillment URLs may land in raw but **must be hashed before staging/marts**.
- **PII must never cross the `raw → staging` boundary unhashed.**
- **Customer linkage uses `SHA-256(lower(trim(email)) || PII_SALT)`** (dbt macro `hash_pii.sql`). `PII_SALT` is generated once and backed up offline — losing it breaks all customer linkage.
- **The public portfolio must use fully synthetic data only.** No sanitized real-customer data, ever.
- **Never commit:** API keys, service-account JSON, tracking IDs, customer emails, phone numbers, names, or addresses.

---

## 6. Agent workflow (Superpowers)

All coding agents must use the Superpowers-style workflow for code changes. Do not jump straight to writing implementation code.

1. **Inspect first** — read the relevant docs and the current state of the files you will touch.
2. **Design / refine before implementing** — use brainstorming/design refinement to confirm intent and approach against the specs before writing code.
3. **Make a small implementation plan** — list the files and the order you'll build them.
4. **Prefer TDD** — write or adjust tests before or alongside the code (parsing, privacy/PII-drop, idempotency are the priority test targets).
5. **Implement in small, reviewable increments** — not one giant change.
6. **Run formatters and tests after each meaningful change.**
7. **Verify acceptance criteria from `TASKS.md`** for the work you did.
8. **Update `TASKS.md` checkboxes only after verification** — and only the boxes you actually verified.
9. **Do not mark a task done just because files were created.** Created ≠ done. Done = verified against acceptance criteria.
10. **Do not skip tests** unless you explicitly justify it in your final report.

---

## 7. Phase discipline

- **Do not jump to Phase 1+ unless explicitly instructed.** Stay on the current phase.
- **Phase 0:** implement only setup / privacy / source-audit scaffolding.
- **Phase 1:** `docs/WOO_PAYLOAD_AUDIT.md` must be filled from **real WooCommerce API responses** before finalizing any dbt staging assumptions (variant parsing, payment-fee field, shipping-charged field, refund grain, custom statuses). No "TBD" left in the audit.
- **Phase 6:** `docs/GA4_BIGQUERY_AUDIT.md` gates attribution. GA4↔Woo `transaction_id` join is enabled only when the audit records ≥85% match rate; otherwise GA4 is behavior/funnel/landing only.

See `docs/ROADMAP.md` for the full phase-by-phase goals, outputs, and acceptance criteria.

---

## 8. Coding standards

- **Python 3.11+.**
- **Clear module boundaries:** `src/extract/`, `src/load/`, `src/utils/`.
- **Python EL extracts and loads only — business logic belongs in dbt.**
- **Configuration via environment variables** through `.env` / `python-dotenv`. Never hardcode secrets or connection details.
- **Idempotent design** — re-running an extractor/loader must not create duplicates (upsert on natural keys, e.g. `(site_code, woo_<entity>_id)`; advance watermarks only on success).
- **Type hints** where practical.
- **Tests for parsing, privacy (PII drop / hashing), and idempotency** are required, not optional.
- **Use `ruff` / `black` if configured.** Otherwise do not introduce unrelated tooling without documenting why in your final report.
- Keep files focused and small; organize by feature/domain.

---

## 9. Expected commands

Planned commands for the project (from `TASKS.md` / `docs/PIPELINE_DESIGN.md`):

```bash
docker compose up -d postgres   # Postgres 16 in Docker
dbt deps                        # install dbt_utils + dbt_expectations (run from dbt/)
dbt debug                       # verify Postgres connection / profile
dbt seed                        # load seeds
dbt build                       # run + test all models
pytest -q                       # Python test suite
```

**These may not all work until Phase 0 scaffolding is complete** (no `docker-compose.yml`, dbt project, or Postgres exists yet). If a command can't run, say so in your report rather than faking success.

---

## 10. Phase 0 acceptance criteria

Phase 0 is complete when (summarized from `TASKS.md` and `docs/ROADMAP.md`):

- [ ] A strict `.gitignore` exists (`.env`, `data/raw/`, `Order Management.csv`, `dbt/target/`, `dbt/dbt_packages/`, `__pycache__/`, `.venv/`, `*.pbix.backup`).
- [ ] `.env.example` exists with placeholders (no real secrets).
- [ ] `docker-compose.yml` starts Postgres 16.
- [ ] The required schemas can be created: `raw`, `staging`, `marts_core`, `marts_marketing`, `marts_operations`, `marts_recon`.
- [ ] A dbt project exists and `dbt debug` can connect.
- [ ] `config/sites.yaml` exists.
- [ ] `dbt/seeds/dim_site_seed.csv` mirrors `config/sites.yaml` (and ideally a test asserts they match).
- [ ] Seed placeholders exist for: country ISO map, FX rates, supplier, payment fee.
- [ ] `git status` does **not** show: the real `Order Management.csv`, `.env`, `data/raw/`, `dbt/target/`, `dbt/dbt_packages/`, or any secrets.

---

## 11. Final response format

Every implementation session must end with a report containing:

1. **Files changed** — what was created/modified.
2. **Commands run and their results** — actual output, not assumed.
3. **Tests** — which passed, which failed.
4. **`TASKS.md` items completed** — only verified ones.
5. **Risks / follow-ups** — open questions, deferred work, anything fragile.
6. **Privacy confirmation** — explicit statement that no private data or secrets were committed (no real CSV, `.env`, `data/raw/`, keys, tracking IDs, or customer PII).
