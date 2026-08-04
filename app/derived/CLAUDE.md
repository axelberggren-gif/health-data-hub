> **Canon** — current source of truth for this directory. If reality and this file disagree,
> fix this file in the same PR.

# app/derived/ — the derived layer

## Purpose
Turn the canonical store into the pre-digested shapes the dashboard and the insight engine
read: daily rollups, personal baselines, the readiness score, and anomaly flags. It is a
**consumer, not a source** (tech spec D2) — it reads canonical tables and writes derived ones,
and implements no `HealthDataSource` because there is nothing external to sync.

## Key files
- `dates.py` — day attribution. Pure functions mapping each canonical row to the **local**
  date it belongs to, plus the night window used to aggregate a night's air readings.
  Everything else in this package is keyed by what these functions return.

Landing in M2: `rollup.py`, `baselines.py`, `readiness.py`, `anomalies.py`, `jobs.py`.

## Conventions
- Rollup/scoring functions are **pure** (`rows -> values`) so they can be unit-tested against
  hand-computed values; only `jobs.py` touches the session and commits.
- Timestamps: canonical rows store **UTC**, and SQLite hands them back *naive*. Always
  normalize with `dates.as_utc()` — a naive datetime is UTC, never local. Reading it as local
  shifts a whole night onto the wrong date.
- The local calendar comes from `Settings.home_timezone`; never hard-code a zone or an offset.
- Per-record `timezone_offset` is ignored in V1 (one user, one home zone). Travel-aware
  attribution is a later pass.

## Invariants (do not break)
- Writes to derived tables go through `app.sync.orchestrator.upsert()` with `source="derived"`
  and a deterministic `source_external_id` (the ISO date), so recomputation is idempotent by
  construction — the house invariant applies here exactly as it does to sources.
- This package must not import from `app.sources` or `app.api`; it depends on `app.models`,
  `app.sync` and `app.config` only.
- Day attribution lives **here**, in one place. Anything that needs "which day is this?" calls
  `dates.py` rather than re-deriving it.

## Recent changes
- V1 M1: created the package with `dates.py` — wake-date attribution for sleep, linked-sleep
  attribution for recovery (with a `recorded_at` fallback), start-date attribution for
  workouts/cycles, the nap-excluding nightly selector, and `night_window()`. Guarded by
  `tests/test_dates.py` (M1-T01…T08), which covers both DST transitions.
