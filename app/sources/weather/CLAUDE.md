> **Canon** — current source of truth for this directory. If reality and this file disagree,
> fix this file in the same PR.

# app/sources/weather/ — Open-Meteo weather & daylight

## Purpose
Outdoor temperature, precipitation and daylight for the home location (A4), so the derived
layer can ask whether dark February weeks or a 24 °C bedroom night explain a bad week. Tech
spec D7.

## Key files
- `client.py` — `fetch_daily(url, ...)`: one day-range request. `DAILY_FIELDS` is what we ask
  Open-Meteo for.
- `mapper.py` — `parse_daily(payload, tz)` → `(rows, problems)`. Defensive, per-day parsing.
- `source.py` — `OpenMeteoSource` (`name = "open_meteo"`), the endpoint split and the cursor.

## Conventions
- Requests pass `timezone=Settings.home_timezone`, so Open-Meteo buckets days in the same
  local calendar the derived layer uses (D1). `sunrise` / `sunset` come back as naive local
  strings and are stored as UTC instants.
- Two hosts, one shape: the forecast endpoint covers roughly the last `FORECAST_PAST_DAYS`
  (90) days plus the forecast, the archive endpoint covers deep history. A range that
  straddles the boundary is split into one request per host, so a six-month backfill
  (`BACKFILL_DAYS = 183`) costs two calls, not 183.

## Invariants (do not break)
- **An unset location means off.** With `home_lat == home_lon == 0.0` the source makes *zero*
  HTTP calls and returns an empty `SyncResult` with a note. Open-Meteo answers happily for
  0.0/0.0 (the Gulf of Guinea); recording that as the owner's weather would be worse than
  recording nothing.
- Parsing is per-day and never raises on a bad payload: an unplaceable day is skipped with a
  `SyncResult.notes` entry, and a day missing one metric still lands with that column null.
  A single bad row must not stall the cursor and silently freeze the source.
- The cursor advances to the **newest date actually written**, not to today, so a day the API
  had no data for is retried on the next run.
- No credentials exist for this source — if one ever does, it comes from `Settings`.

## Recent changes
- V1 M3: created the package (`OpenMeteoSource`, `weather_daily`). See ADR-0011.
