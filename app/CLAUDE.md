> **Canon** — current source of truth for this directory. If reality and this file disagree,
> fix this file in the same PR.

# app/ — the FastAPI application

## Purpose
The whole backend: configuration, the canonical data model, the source-ingestion seam, sync
orchestration, the HTTP API, and export. Data flows: **source adapter → normalize → canonical
store (`models.py`) → consumers (export, future insights)**.

## Key files
- `main.py` — FastAPI app + lifespan (`init_db()` on startup; optional Mill poller). Mounts the
  routers in `api/`.
- `config.py` — `Settings` (pydantic-settings); the ONLY place secrets/config enter the app.
- `db.py` — engine, `SessionLocal`, `Base`, `get_db()` dependency, `init_db()` (dev `create_all`;
  production uses Alembic).
- `models.py` — the canonical schema (recovery, sleep + stages, workout, cycle, profile, body,
  air quality, vitals) + the `SourceRecord` provenance mixin, and the *derived* tables
  (`daily_summary`, `baseline`, `insight_card`) written only by `derived/`.
- `scheduler.py` — background jobs: the optional Mill poller and the daily derivation tick
  (plus a startup catch-up when the derived layer has gone stale).
- Sub-packages: `sources/`, `sync/`, `derived/`, `api/`, `export/` — each has its own
  `CLAUDE.md`.

## Conventions
- New runtime deps go in `requirements.txt`; dev/CI tooling in `requirements-dev.txt`.
- `from __future__ import annotations` at the top of modules; type with `Mapped[...]` for ORM.
- Read config via `get_settings()`, never `os.environ` directly in business logic.

## Invariants (do not break)
- Secrets only via `Settings` (config.py). No hard-coded credentials anywhere.
- The canonical model in `models.py` is the contract consumers depend on — change it through a
  migration-aware path and an ADR (see `docs/decisions/`), not ad hoc.

## Recent changes
- V1 M1 + M2: added `derived/` — the layer that rolls the canonical store up into one
  `daily_summary` row per local date, plus baselines, readiness and anomaly flags. New tables
  `daily_summary` / `baseline` / `insight_card` and `sleep_session.sleep_debt_ms` ship in
  Alembic revision `0002`; `Settings` gained `derived_schedule_enabled` / `derived_run_hour`.
  See ADR-0009.
- V1 M0: Alembic migrations are now the only way to change an existing table (`alembic/`,
  `make migrate`, revision `0001` = the current schema); `Settings` gained the V1 fields
  (`app_token`, `home_timezone`, `home_lat`/`home_lon`, `anthropic_api_key`, `llm_*`), all
  defaulting to safe/off. See ADR-0008.
- Added AI-first CI/guardrail pipeline + tests scaffold (initial setup).
