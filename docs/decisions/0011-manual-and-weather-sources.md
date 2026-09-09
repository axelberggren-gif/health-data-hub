# 0011 — Manual input and weather are ordinary sources

- **Status:** Accepted
- **Date:** 2026-09-09

> Numbering note: ADR-0010 is claimed by the open PR that widens the reviewer's `CLAUDE.md`
> carve-out. This one takes 0011 so the two can land in either order.

## Context

V1 M3 adds two kinds of data that don't look like WHOOP or Mill:

- **The daily log.** How the day felt (mood, energy, stress, soreness), what was drunk, when
  the last coffee was, which supplements were taken. It comes from the owner tapping a form,
  not from an API.
- **Weather and daylight.** A free, keyless public API (Open-Meteo) that will answer for any
  coordinates you hand it.

The tempting shortcut for the first is a route that writes to a table directly — it is three
lines shorter. The tempting shortcut for the second is "it's just weather, no credentials, no
seam needed".

Both shortcuts break the same thing. `app/sync/orchestrator.upsert()` on
`(source, source_external_id)` is the repo's second global invariant, and it holds *because*
there is exactly one write path. A route that inserts a check-in directly is a second write
path, and the first re-submitted form is a duplicate row that the rollup then has to pick
between.

This also settles a question the tech spec left implicit: whether these new inputs reach
`daily_summary`, and whether either of them is enough on its own to make a day exist.

## Decision

1. **Both are `HealthDataSource` implementations**, registered in `app/sources/registry.py`
   like every other adapter.
   - `manual` (`app/sources/manual/`) — `capabilities() == {"checkin", "intake"}`. Its
     `backfill()` / `sync_incremental()` are deliberate no-ops: nothing external exists to
     pull. Data arrives by `POST /log/*`, which is the same role `handle_webhook()` plays for
     a push-based source. The routes validate and resolve the date; the source maps and
     writes.
   - `open_meteo` (`app/sources/weather/`) — a normal pull adapter with a cursor.
2. **Identity keys**, both enforced by a `(source, source_external_id)` unique constraint:
   - check-in → `checkin:<ISO local date>`, so the form is editable rather than append-only;
   - intake event → the **client-generated UUID**, because only the phone knows whether a
     POST is a retry;
   - weather → the ISO local date.
3. **An unset home location disables the weather source**, with zero HTTP calls. `home_lat`
   and `home_lon` default to `0.0`, which Open-Meteo treats as a real place in the Gulf of
   Guinea. A source that silently records the wrong hemisphere's weather for six months is
   worse than one that records nothing.
4. **Check-in and weather flow into `daily_summary`**, with an asymmetry: a **check-in alone
   makes a day worth summarizing; weather alone does not.** Logging how a day felt is
   something that happened. Weather happened whether or not the owner was measured, so
   counting it would manufacture a summary row for every date the source has ever covered —
   the empty-rows failure tech spec §5.1 exists to prevent.
5. **`biomarker` and `nutrition_entry` ship empty** — in the schema and the migration, with
   no writer, no route and no UI. Reserving the shape now means adding labs or food later is
   an adapter plus a form, not a migration against months of live data.
6. **`app/sources/localtime.py`** holds the two local-calendar helpers the date-keyed
   adapters share (`home_tz`, `local_midnight_utc`). `app/derived/dates.py` has richer
   versions, but the layering forbids a source from importing the derived layer, so this
   small duplication is the deliberate price of that direction.

## Consequences

**Easier.** Every V1 input now has one write path, one identity rule and one place to look.
A future Apple Health check-in importer writes `checkin_daily` under `source="healthkit"`
and the rollup picks it up unchanged — it reads the canonical table, not the source. Weather
from a second provider is additive: `weather_daily.date` is unique *per source*, so two
providers disagreeing about a day is data, not a conflict.

**Harder.** `POST /log/checkin` is a route, a Pydantic model and a source method rather than
one function. That indirection is the invariant, not ceremony.

**To revisit.** (a) The `manual` source's inert `backfill()`/`sync_incremental()` mean
`POST /sync/manual/backfill` succeeds and does nothing — honest, but it may deserve a 400
once the API surface is user-facing. (b) `FORECAST_PAST_DAYS = 90` is Open-Meteo's
approximate forecast-endpoint reach, not a documented guarantee; if backfills start losing
their oldest days, that constant is the first suspect. (c) The archive endpoint lags real
time by a few days, so the most recent dates in a long backfill may come back empty and be
re-fetched next run — which the data-following cursor already handles.
