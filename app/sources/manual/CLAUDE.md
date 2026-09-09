> **Canon** — current source of truth for this directory. If reality and this file disagree,
> fix this file in the same PR.

# app/sources/manual/ — the daily log as a data source

## Purpose
The owner's own input (A3 check-in, A5 alcohol/caffeine, A10 supplements) enters the
canonical store through the *same* seam as WHOOP and Mill, not through a side door. See
tech spec D3.

## Key files
- `source.py` — `ManualSource` (`name = "manual"`), `checkin_key(day)`, and the two write
  paths the `/log` routes call: `record_checkin(day, values)` and
  `record_intake(client_id, values)`.

## Conventions
- The HTTP layer (`app/api/routes_log.py`) validates and resolves the date; the mapping and
  the write live here. A route never calls `upsert()` directly.
- `record_checkin` writes only the keys it is given, so a partial submission corrects one
  field instead of blanking the rest of the day.

## Invariants (do not break)
- A check-in's `source_external_id` is `checkin:<ISO local date>` — one row per day, always
  editable. An intake event's is the **client-generated UUID**, so a retried POST cannot
  double-log.
- `backfill()` and `sync_incremental()` stay no-ops returning an empty `SyncResult`: there is
  nothing external to pull. Data arrives by POST, the way `handle_webhook()` is the arrival
  path for a push-based source.
- Everything else in `app/sources/CLAUDE.md` applies unchanged — this package narrows nothing
  and grants itself no exception.

## Recent changes
- V1 M3: created the package (`ManualSource`, `checkin_daily` + `intake_event`). See ADR-0011.
