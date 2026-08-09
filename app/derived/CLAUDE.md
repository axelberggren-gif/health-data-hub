> **Canon** — current source of truth for this directory. If reality and this file disagree,
> fix this file in the same PR.

# app/derived/ — the derived layer (day attribution, rollups, readiness, baselines, flags)

## Purpose
Turn the canonical store into **one row per local date** plus the first conclusions drawn from
it. This is a *consumer that persists*, not a data source: nothing here syncs anything
external. See ADR-0009.

Pipeline: `canonical tables → summarize_date → daily_summary → baselines → flags + cards`.

## Key files
- `dates.py` — day attribution (tech spec D1): `sleep_wake_date`, `event_local_date`,
  `attribute_recovery`, `night_sleep_for_date`, `night_window`, `night_air_readings`.
- `rollup.py` — pure `rows -> values` aggregations + `summarize_date(db, day)`.
- `readiness.py` — `air_score()` and `compute_readiness()` (§6). Weights and penalties are
  module constants, so tuning is one edit plus its golden tests.
- `baselines.py` — `recompute_baselines()`, `window_values()`, `z_score()` (§7).
- `flags.py` — the anomaly rules, the illness conjunction, and card lifecycle (§8).
- `jobs.py` — `run_daily_derivation(db, days_back, today=None)` and `catch_up_if_stale(db)`.

Entry points are `POST /derived/run` (`app/api/routes_derived.py`) and the scheduler tick in
`app/scheduler.py` — **not** the source registry.

## Conventions
- Every `date` key is a **local** date in `Settings.home_timezone`. Never bucket by the UTC
  date, and treat a naive datetime read back from SQLite as UTC (`dates.as_utc`).
- Aggregation helpers stay pure (`rows -> values`) so they are testable without a database;
  queries live in `summarize_date` and the `_*_for_date` helpers.
- `SessionLocal` has **autoflush off**. A step whose output the next step reads back must
  `db.flush()` before returning. Only the job commits.
- Thresholds and weights are named module constants, never literals inside a rule.

## Invariants (do not break)
- Writes go through `app.sync.orchestrator.upsert()` with `source="derived"` and a
  deterministic `source_external_id` (ISO date for summaries, a finding key for cards), so
  re-running is idempotent. See `tests/test_derived_job.py`.
- Baseline windows **exclude the day being judged**; z-scores need `n >= 14` and `sd > 0`.
- Readiness is `None` when recovery is missing or `user_calibrating` — never invented — and
  always stores the components and weights actually used.
- A date with no upstream data gets **no** summary row.
- Illness-warning wording stays **non-diagnostic**: it describes measurements, never a
  condition.
- Nothing in `app/sources/` may import from here; this layer reads canonical models and does
  not care which adapter produced them.

## Recent changes
- V1 M1 + M2: created the layer — day attribution (`dates.py`), the rollup, readiness,
  baselines, flags and the derivation job, with `daily_summary` / `baseline` / `insight_card`
  landing in Alembic revision `0002`. See ADR-0009.
