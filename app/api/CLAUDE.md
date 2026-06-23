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
- Added exception chaining (`raise ... from exc`) for clearer errors (initial setup).
