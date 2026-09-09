> **Canon** — current source of truth for this directory. If reality and this file disagree,
> fix this file in the same PR.

# app/api/ — FastAPI routers

## Purpose
The HTTP surface: OAuth connect flow, sync triggers, export, health check, Mill diagnostics.

## Key files
- `routes_oauth.py` — WHOOP OAuth: `/auth/whoop/login` (redirect) + `/auth/whoop/callback`
  (validates CSRF `state`, exchanges code, stores tokens in `WhoopConnection`).
- `routes_sync.py` — `/sync/{source}/backfill` + `/sync/{source}/incremental`; resolves the
  source via the registry.
- `routes_export.py` — JSON/CSV export over the canonical store.
- `routes_derived.py` — `POST /derived/run?days_back=N`: recompute daily summaries, baselines
  and flags, returning per-step counts. The manual "refresh" companion to the scheduler tick.
- `routes_log.py` — the daily log: `POST /log/checkin` (upsert today's or `?date=`'s
  check-in) and `POST /log/intake` (idempotent on the caller's `client_id`). Validates and
  resolves the date, then hands the values to the `manual` source — it never writes directly.
- `routes_health.py` — `GET /health` → `{"status": "ok"}`.
- `routes_mill.py` — Mill diagnostics.

## Conventions
- Routers use `APIRouter(prefix=..., tags=[...])` and the `get_db` dependency.
- Convert internal errors to `HTTPException` with `raise ... from exc` (preserve the cause).
- Get config via `get_settings()`.

## Invariants (do not break)
- Every OAuth callback **validates the CSRF `state`** before exchanging a code.
- Tokens are never logged or returned beyond what a response strictly needs.
- Secrets come from `Settings`, never hard-coded or read from the request.
- The dev-only in-memory `state` store in `routes_oauth.py` must move to signed cookies / Redis
  before any multi-process or production deployment.

## Recent changes
- V1 M3: added `routes_log.py` (`POST /log/checkin`, `POST /log/intake`) behind
  `require_token`, with `/log/checkin` appended to `PROTECTED_ROUTES` in `tests/test_auth.py`
  (M3-T09). See ADR-0011.
- V1 M2: added `routes_derived.py` (`POST /derived/run`), mounted behind `require_token` and
  added to `PROTECTED_ROUTES` in `tests/test_auth.py` rather than tested separately.
- V1 M0: added `deps.py` with `require_token` — the shared-token auth wall (ADR-0008). It is
  mounted on the whole `/export` router; `/dashboard`, `/log` and `/insights` must mount the
  same dependency as they land. Empty `Settings.app_token` disables it (local-dev default);
  `/health` and `/` stay public.
- Added exception chaining (`raise ... from exc`) for clearer errors (initial setup).
