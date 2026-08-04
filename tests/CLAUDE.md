> **Canon** — current source of truth for this directory. If reality and this file disagree,
> fix this file in the same PR.

# tests/ — the safety net

## Purpose
Fast, hermetic tests that guard the invariants and prove the app boots. CI runs `pytest` as a
required check.

## Key files
- `conftest.py` — repoints `DATABASE_URL` at a **throwaway temp SQLite file before importing the
  app**, so tests never touch the real `health.db`. Provides `db` (session), `clean_db`
  (session with the day-scoped tables emptied) and `client` (TestClient) fixtures. Also sets
  `DERIVED_SCHEDULE_ENABLED=false` so booting the app in a test never derives underneath it.
- `factories.py` — the shared fixture builders (TEST_SPEC rule 5): `make_sleep`,
  `make_recovery`, `make_cycle`, `make_workout`, `make_air_reading`, `make_summary`, plus
  `local()` / `utc()` helpers. Timestamps are Europe/Stockholm local unless already aware.
- `test_smoke.py` — boots the app via TestClient (the "does it actually start?" check) and hits
  `/` and `/health`.
- `test_orchestrator_idempotency.py` — guards INVARIANT #2 (idempotent upsert + the DB unique
  constraint).

## Conventions
- Tests make **no real network calls** and use **no real credentials** — ever. Mock HTTP if a
  test needs a source client.
- Use distinct `source_external_id`s per test to avoid cross-test row collisions on the shared
  temp DB. That is not enough for anything keyed by **date** (rollups, baselines, flags) —
  those tests take the `clean_db` fixture instead, which empties the day-scoped tables first.
- Statistical expectations are **hand-computed**, never snapshotted: pick fixture series whose
  mean and SD have closed forms (a consecutive-integer ramp, or half the days at each of two
  values) so a threshold can be asserted exactly.
- New logic in `app/sources/`, `app/sync/`, or `app/export/` should come with a test (or the PR
  explains why not).

## Invariants (do not break)
- Always ≥1 collectable test (so `pytest` never exits 5 / "no tests").
- Never read the real `.env` or `health.db` from a test.

## Recent changes
- V1 M1 + M2: added `factories.py` (shared builders), the `clean_db` fixture, and
  `test_dates.py` (M1-T01…T08), `test_derived_job.py`, `test_readiness.py`,
  `test_baselines.py`, `test_flags.py` (M2-T01…T11) plus `test_scheduler.py` for the
  derivation tick. `/derived/run` was appended to `PROTECTED_ROUTES`.
- V1 M0: added `test_migrations.py` (M0-T01 — Alembic head must equal `Base.metadata`),
  `test_config_defaults.py` (M0-T02) and `test_auth.py` (M0-T03/T04). `test_auth.py` holds a
  `PROTECTED_ROUTES` list that later milestones **extend** with `/dashboard`, `/log` and
  `/insights` rather than duplicating the auth test (per TEST_SPEC M0-T04).
- Added the initial smoke + idempotency tests (initial setup).
