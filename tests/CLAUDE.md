> **Canon** — current source of truth for this directory. If reality and this file disagree,
> fix this file in the same PR.

# tests/ — the safety net

## Purpose
Fast, hermetic tests that guard the invariants and prove the app boots. CI runs `pytest` as a
required check.

## Key files
- `conftest.py` — repoints `DATABASE_URL` at a **throwaway temp SQLite file before importing the
  app**, so tests never touch the real `health.db`. Provides `db` (session) and `client`
  (TestClient) fixtures.
- `test_smoke.py` — boots the app via TestClient (the "does it actually start?" check) and hits
  `/` and `/health`.
- `test_orchestrator_idempotency.py` — guards INVARIANT #2 (idempotent upsert + the DB unique
  constraint).

## Conventions
- Tests make **no real network calls** and use **no real credentials** — ever. Mock HTTP if a
  test needs a source client.
- Use distinct `source_external_id`s per test to avoid cross-test row collisions on the shared
  temp DB.
- New logic in `app/sources/`, `app/sync/`, or `app/export/` should come with a test (or the PR
  explains why not).

## Invariants (do not break)
- Always ≥1 collectable test (so `pytest` never exits 5 / "no tests").
- Never read the real `.env` or `health.db` from a test.

## Recent changes
- V1 M1: added `factories.py` (TEST_SPEC rule 5) — committed-row builders (`make_sleep`,
  `make_recovery`, `make_cycle`, `make_workout`, `make_air_reading`) plus `local()` / `utc()`
  helpers. They normalize every timestamp to UTC, because that is how canonical rows are
  stored. They also **commit**, so rows outlive their test: query-by-date tests must use a
  date no other test uses. `test_dates.py` holds M1-T01…T08.
- V1 M0: added `test_migrations.py` (M0-T01 — Alembic head must equal `Base.metadata`),
  `test_config_defaults.py` (M0-T02) and `test_auth.py` (M0-T03/T04). `test_auth.py` holds a
  `PROTECTED_ROUTES` list that later milestones **extend** with `/dashboard`, `/log` and
  `/insights` rather than duplicating the auth test (per TEST_SPEC M0-T04).
- Added the initial smoke + idempotency tests (initial setup).
