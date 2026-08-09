> **Canon** — current source of truth for this directory. If reality and this file disagree,
> fix this file in the same PR.

# app/sources/ — the pluggable data-source seam

## Purpose
Every health data source lives here and implements one interface, so new sources plug in without
touching the store, sync, or export layers.

## Key files
- `base.py` — the `HealthDataSource` ABC (the contract) + `SyncResult`. **This is an
  architectural seam: changing it requires an ADR.**
- `registry.py` — `_SOURCES` map + `get_source(name, db)` / `available_sources()`. New adapters
  register here.
- `whoop/` — the WHOOP source: `oauth`, `client` (pagination + 429 backoff), `mapper`
  (WHOOP → canonical), `source` (`WhoopApiSource`).
- `mill/` — the Mill Sense source: `auth`, `client`, `history`, `mapper`, `source`
  (`MillSenseSource`) — indoor air quality.

## Conventions
- A source's `__init__` takes the DB session (`db`); construction happens via the registry.
- Adapters parse untyped JSON from `httpx`; keep parsing defensive and inside the adapter.
- mypy is intentionally lenient for `app.sources.*` (untyped third-party payloads) — tighten
  per-module as types firm up.

## Invariants (do not break)
- A source **subclasses `HealthDataSource`** and implements `capabilities()`, `backfill()`,
  `sync_incremental()`.
- A source maps native payloads → **canonical models** (`app/models.py`); it does **not** import
  from `app.sync`, `app.export`, or manage DB transactions itself — it hands values to the
  orchestrator's `upsert()`.
- Tokens/credentials are read from `Settings`; never logged, never committed.

## Recent changes
- V1 M2: the WHOOP sleep mapper now carries `sleep_debt_ms`
  (`score.sleep_needed.need_from_sleep_debt_milli`) into the canonical model, so the derived
  layer never has to read a source payload out of `raw`. The derived layer is not a source and
  is not registered here — see ADR-0009.
- Documented the seam + invariants (initial setup).
