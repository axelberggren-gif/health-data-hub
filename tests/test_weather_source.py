"""The Open-Meteo weather source (docs/specs/TEST_SPEC_V1.md, M3 — decision D7).

Weather is the one V1 source with no credentials and no account, which makes it the easiest
one to get subtly wrong: it will happily answer for coordinates 0.0/0.0 (a spot in the Gulf
of Guinea) instead of refusing. So the first thing pinned here is that an unset location
means *off*, not a guess — asserted by the HTTP mock never being called.

Every test is hermetic: `httpx.Client` is replaced by a recorder that returns a checked-in
fixture with fabricated values in the real response *shape*. Nothing here touches a network.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.models import WeatherDaily
from app.sources.base import HealthDataSource
from app.sources.registry import available_sources, get_source
from app.sources.weather import client as weather_client
from app.sync.orchestrator import get_cursor

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "open_meteo_daily.json").read_text())

#: The placeholder coordinates the fixture was built around (not a real location).
TEST_LAT = 12.25
TEST_LON = 34.5

#: The fixture's three days, in Europe/Stockholm. Deliberately in the past relative to any
#: run of this suite, so "sync everything after the cursor" is always a non-empty window.
FIXTURE_DATES = [date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 3)]


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    """Stands in for `httpx.Client`, recording every request instead of making it."""

    def __init__(self, recorder: SimpleNamespace) -> None:
        self._recorder = recorder

    def __enter__(self) -> _FakeClient:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def get(self, url: str, params: dict | None = None) -> _FakeResponse:
        self._recorder.calls.append({"url": url, "params": dict(params or {})})
        return _FakeResponse(self._recorder.payload)


@pytest.fixture
def http(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Replace the adapter's HTTP client with a recorder returning the fixture payload."""
    recorder = SimpleNamespace(calls=[], payload=FIXTURE)
    monkeypatch.setattr(
        weather_client.httpx, "Client", lambda *a, **k: _FakeClient(recorder)
    )
    return recorder


@pytest.fixture
def home_coords(monkeypatch: pytest.MonkeyPatch):
    """Settings with a configured home location, so the source is enabled."""
    monkeypatch.setenv("HOME_LAT", str(TEST_LAT))
    monkeypatch.setenv("HOME_LON", str(TEST_LON))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def no_home_coords():
    """Settings at their defaults (0.0 / 0.0), which must disable the source."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _rows(db) -> list[WeatherDaily]:
    db.rollback()
    return list(db.execute(select(WeatherDaily).order_by(WeatherDaily.date)).scalars().all())


def _earliest_start(calls: list[dict]) -> str:
    """The oldest date any request in this sync asked for."""
    return min(call["params"]["start_date"] for call in calls)


def test_weather_parses_a_daily_payload(clean_db, home_coords, http) -> None:
    """M3-T04: a 3-day payload becomes 3 rows, with the configured coordinates requested."""
    source = get_source("open_meteo", clean_db)
    result = source.backfill(datetime(2026, 7, 1, tzinfo=UTC), datetime(2026, 7, 3, tzinfo=UTC))

    assert result.counts == {"weather": 3}
    assert http.calls, "the adapter made no HTTP request"
    assert all(call["params"]["latitude"] == TEST_LAT for call in http.calls)
    assert all(call["params"]["longitude"] == TEST_LON for call in http.calls)

    rows = _rows(clean_db)
    assert [r.date for r in rows] == FIXTURE_DATES
    assert [r.temp_min_c for r in rows] == [11.2, 12.6, 14.0]
    assert [r.temp_max_c for r in rows] == [21.4, 19.8, 24.1]
    assert [r.daylight_seconds for r in rows] == [66480, 66360, 66240]
    assert [r.source for r in rows] == ["open_meteo"] * 3
    assert [r.source_external_id for r in rows] == [d.isoformat() for d in FIXTURE_DATES]

    # Sunrise/sunset arrive as naive *local* strings and are stored as UTC instants:
    # 2026-07-01T03:38 in Europe/Stockholm (UTC+2 in July) is 01:38Z.
    first = rows[0].sunrise
    assert (first.hour, first.minute) == (1, 38)


def test_weather_skips_a_malformed_day_without_raising(clean_db, home_coords, http) -> None:
    """M3-T04: a bad date and a truncated metric array cost one day, not the whole sync."""
    http.payload = {
        "daily": {
            "time": ["2026-07-11", "not-a-date", "2026-07-13"],
            "temperature_2m_min": [10.0, 11.0, 12.0],
            "temperature_2m_max": [20.0, 21.0],  # truncated: no entry for the third day
            "precipitation_sum": [0.0, 0.0, 0.0],
            "sunrise": ["2026-07-11T03:45", "2026-07-12T03:46", "2026-07-13T03:47"],
            "sunset": ["2026-07-11T22:00", "2026-07-12T22:00", "2026-07-13T21:58"],
            "daylight_duration": [65000.0, 64900.0, 64800.0],
        }
    }
    source = get_source("open_meteo", clean_db)
    result = source.backfill(datetime(2026, 7, 11, tzinfo=UTC), datetime(2026, 7, 13, tzinfo=UTC))

    assert result.counts == {"weather": 2}
    assert result.notes, "a skipped day must be reported, not swallowed"

    rows = _rows(clean_db)
    assert [r.date for r in rows] == [date(2026, 7, 11), date(2026, 7, 13)]
    # The partial day still lands; only the unreadable metric is null.
    assert rows[1].temp_min_c == 12.0
    assert rows[1].temp_max_c is None


def test_weather_is_disabled_without_coordinates(clean_db, no_home_coords, http) -> None:
    """M3-T05: at the default 0.0/0.0 the source does nothing and calls nothing."""
    settings = get_settings()
    assert (settings.home_lat, settings.home_lon) == (0.0, 0.0)

    source = get_source("open_meteo", clean_db)
    result = source.sync_incremental()

    assert result.counts == {}
    assert result.notes  # says *why* it did nothing
    assert http.calls == []
    assert _rows(clean_db) == []


def test_weather_cursor_advances_and_narrows_the_next_request(
    clean_db, home_coords, http
) -> None:
    """M3-T06: after syncing through D the next sync asks only for dates after D."""
    source = get_source("open_meteo", clean_db)

    source.sync_incremental()
    assert get_cursor(clean_db, "open_meteo", "weather").date() == date(2026, 7, 3)

    first_sync_calls = len(http.calls)
    source.sync_incremental()
    second_sync_calls = http.calls[first_sync_calls:]

    assert second_sync_calls, "the second sync made no request"
    assert _earliest_start(second_sync_calls) == "2026-07-04"


def test_weather_source_honors_the_seam(clean_db) -> None:
    """M3-T04: the adapter is a normal registered source, not a special case."""
    source = get_source("open_meteo", clean_db)

    assert isinstance(source, HealthDataSource)
    assert source.name == "open_meteo"
    assert source.capabilities() == {"weather"}
    assert "open_meteo" in available_sources()
