"""OpenMeteoSource — outdoor weather and daylight for the home location (A4, D7).

Three things shape this adapter:

* **An unset location means off.** Coordinates default to 0.0/0.0, which is a real place as
  far as the API is concerned. The source refuses to sync rather than quietly recording the
  weather in the Gulf of Guinea for six months.
* **Two endpoints, one shape.** Open-Meteo's forecast host only reaches ~90 days back; deep
  history comes from the archive host. A range that straddles the boundary is split into
  one request per host, which is why a six-month backfill costs two calls, not 180.
* **The cursor follows the data, not the clock.** It advances to the newest date actually
  written, so a day the API had nothing for is retried next run instead of being skipped
  past.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy.orm import Session

from ...config import get_settings
from ...models import WeatherDaily
from ...sync.orchestrator import get_cursor, set_cursor, upsert
from ..base import HealthDataSource, SyncResult
from ..localtime import home_tz, local_midnight_utc
from . import client, mapper

#: The resource name this source's cursor is stored under.
RESOURCE = "weather"

#: Recommended first-run window (tech spec M3: "weather backfills 6 months").
BACKFILL_DAYS = 183

#: How far back an incremental sync reaches when there is no cursor yet.
INCREMENTAL_LOOKBACK_DAYS = 7

#: Roughly how many past days Open-Meteo's *forecast* endpoint serves. Older dates are
#: requested from the archive endpoint instead.
FORECAST_PAST_DAYS = 90


def _as_date(value: datetime) -> date:
    """A stored cursor as a date. SQLite hands back naive datetimes; those are UTC."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).date()


class OpenMeteoSource(HealthDataSource):
    name = "open_meteo"

    def __init__(self, db: Session):
        self.db = db

    def capabilities(self) -> set[str]:
        return {"weather"}

    # ---- sync -------------------------------------------------------------
    def backfill(self, start: datetime, end: datetime | None = None) -> SyncResult:
        zone = home_tz()
        first = start.astimezone(zone).date()
        last = (end or datetime.now(UTC)).astimezone(zone).date()
        return self._sync(first, last)

    def sync_incremental(self) -> SyncResult:
        today = datetime.now(home_tz()).date()
        cursor = get_cursor(self.db, self.name, RESOURCE)
        if cursor is None:
            first = today - timedelta(days=INCREMENTAL_LOOKBACK_DAYS)
        else:
            first = _as_date(cursor) + timedelta(days=1)
        return self._sync(first, today)

    # ---- internals --------------------------------------------------------
    def _sync(self, first: date, last: date) -> SyncResult:
        result = SyncResult(source=self.name, started_at=datetime.now(UTC))
        settings = get_settings()

        if settings.home_lat == 0.0 and settings.home_lon == 0.0:
            result.notes.append(
                "weather is disabled: set HOME_LAT / HOME_LON to your home location"
            )
            result.finished_at = datetime.now(UTC)
            return result

        if first > last:
            result.notes.append(f"nothing to fetch: already synced through {last.isoformat()}")
            result.finished_at = datetime.now(UTC)
            return result

        zone = home_tz()
        written = 0
        newest: date | None = None

        for url, window_start, window_end in self._windows(first, last):
            payload = client.fetch_daily(
                url,
                latitude=settings.home_lat,
                longitude=settings.home_lon,
                timezone=settings.home_timezone,
                start=window_start,
                end=window_end,
            )
            rows, problems = mapper.parse_daily(payload, zone)
            result.notes.extend(problems)
            for day, values in rows:
                # `pollen_index` is intentionally never written: Open-Meteo's pollen
                # coverage is regional and we don't request it. It stays null.
                upsert(
                    self.db,
                    WeatherDaily,
                    source=self.name,
                    source_external_id=day.isoformat(),
                    values={"date": day, "recorded_at": local_midnight_utc(day), **values},
                )
                written += 1
                newest = day if newest is None else max(newest, day)

        result.add(RESOURCE, written)
        if newest is not None:
            set_cursor(
                self.db,
                self.name,
                RESOURCE,
                datetime.combine(newest, time.min, tzinfo=UTC),
            )
        self.db.commit()
        result.finished_at = datetime.now(UTC)
        return result

    def _windows(self, first: date, last: date) -> list[tuple[str, date, date]]:
        """Split `[first, last]` into one `(url, start, end)` per Open-Meteo endpoint."""
        settings = get_settings()
        cutoff = datetime.now(home_tz()).date() - timedelta(days=FORECAST_PAST_DAYS)
        windows: list[tuple[str, date, date]] = []

        if first < cutoff:
            windows.append(
                (settings.open_meteo_archive_url, first, min(last, cutoff - timedelta(days=1)))
            )
        if last >= cutoff:
            windows.append((settings.open_meteo_forecast_url, max(first, cutoff), last))
        return [w for w in windows if w[1] <= w[2]]
