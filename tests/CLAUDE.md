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
- Added the initial smoke + idempotency tests (initial setup).
