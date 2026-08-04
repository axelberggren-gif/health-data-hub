"""Shared fixture builders (TEST_SPEC_V1 rule 5).

Every builder returns a **committed** canonical row with sensible defaults, overridable per
test, and writes through `upsert()` so the fixtures obey the same idempotency invariant as
production code.

**Timestamps.** Canonical rows store instants in **UTC** — that is what the WHOOP mapper
produces, and SQLite drops the offset on write, so anything else silently corrupts the value.
Builders therefore convert whatever they are given to UTC before storing. Use `local(...)` to
express a Europe/Stockholm wall-clock time and `utc(...)` for an explicit UTC instant.

**Collisions.** The suite shares one temp database and these builders commit, so rows outlive
the test that made them. Ids are auto-uniqued per call; tests that query *by date* (rather
than by id) should use a date no other test uses.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from itertools import count
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.models import AirQualityReading, CycleDay, RecoveryDaily, SleepSession, Workout
from app.sync.orchestrator import upsert

HOME_TZ = ZoneInfo("Europe/Stockholm")
WHOOP = "whoop_api"
MILL = "mill_sense"

_counter = count(1)


def local(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    """A Europe/Stockholm wall-clock time, as an aware datetime."""
    return datetime(year, month, day, hour, minute, tzinfo=HOME_TZ)


def utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    """An explicit UTC instant, as an aware datetime."""
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


def _stored(moment: datetime | None) -> datetime | None:
    """Normalize to UTC — the form every canonical timestamp is persisted in."""
    if moment is None:
        return None
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


def _unique(prefix: str) -> str:
    return f"{prefix}-{next(_counter)}"


def make_sleep(
    db: Session,
    *,
    end: datetime,
    start: datetime | None = None,
    nap: bool = False,
    performance: float | None = 80.0,
    efficiency: float | None = 90.0,
    respiratory_rate: float | None = 14.5,
    rem_ms: int | None = 5_400_000,
    slow_wave_ms: int | None = 5_400_000,
    disturbances: int | None = 3,
    external_id: str | None = None,
    source: str = WHOOP,
) -> SleepSession:
    """A sleep session. `end` drives the wake date it will be attributed to."""
    end_utc = _stored(end)
    assert end_utc is not None
    start_utc = _stored(start) if start is not None else end_utc - timedelta(hours=8)
    duration_ms = int((end_utc - start_utc).total_seconds() * 1000)

    obj, _ = upsert(
        db,
        SleepSession,
        source=source,
        source_external_id=external_id or _unique("sleep"),
        values={
            "start": start_utc,
            "end": end_utc,
            "recorded_at": end_utc,
            "nap": nap,
            "sleep_performance_pct": performance,
            "sleep_efficiency_pct": efficiency,
            "respiratory_rate": respiratory_rate,
            "total_in_bed_ms": duration_ms,
            "total_rem_ms": rem_ms,
            "total_slow_wave_ms": slow_wave_ms,
            "disturbance_count": disturbances,
        },
    )
    db.commit()
    return obj


def make_recovery(
    db: Session,
    *,
    score: float | None = 60.0,
    sleep_id: str | None = None,
    hrv: float | None = 55.0,
    rhr: float | None = 52.0,
    spo2: float | None = 96.0,
    skin_temp: float | None = 33.5,
    calibrating: bool = False,
    recorded_at: datetime | None = None,
    external_id: str | None = None,
    source: str = WHOOP,
) -> RecoveryDaily:
    """A recovery score. `sleep_id` is a sleep's `source_external_id` (D1.3)."""
    obj, _ = upsert(
        db,
        RecoveryDaily,
        source=source,
        source_external_id=external_id or _unique("recovery"),
        values={
            "sleep_id": sleep_id,
            "recovery_score": score,
            "hrv_rmssd_ms": hrv,
            "resting_hr_bpm": rhr,
            "spo2_pct": spo2,
            "skin_temp_c": skin_temp,
            "user_calibrating": calibrating,
            "recorded_at": _stored(recorded_at),
        },
    )
    db.commit()
    return obj


def make_cycle(
    db: Session,
    *,
    start: datetime,
    end: datetime | None = None,
    strain: float | None = 12.4,
    kilojoule: float | None = 9_000.0,
    external_id: str | None = None,
    source: str = WHOOP,
) -> CycleDay:
    """A WHOOP physiological cycle — attributed to the local date it STARTS (D1.4)."""
    start_utc = _stored(start)
    assert start_utc is not None
    obj, _ = upsert(
        db,
        CycleDay,
        source=source,
        source_external_id=external_id or _unique("cycle"),
        values={
            "start": start_utc,
            "end": _stored(end) if end is not None else start_utc + timedelta(hours=24),
            "recorded_at": start_utc,
            "strain": strain,
            "kilojoule": kilojoule,
        },
    )
    db.commit()
    return obj


def make_workout(
    db: Session,
    *,
    start: datetime,
    end: datetime | None = None,
    strain: float | None = 8.0,
    sport_name: str | None = "running",
    kilojoule: float | None = 1_500.0,
    external_id: str | None = None,
    source: str = WHOOP,
) -> Workout:
    """A workout — attributed to the local date it STARTS, even if it ends next day."""
    start_utc = _stored(start)
    assert start_utc is not None
    obj, _ = upsert(
        db,
        Workout,
        source=source,
        source_external_id=external_id or _unique("workout"),
        values={
            "start": start_utc,
            "end": _stored(end) if end is not None else start_utc + timedelta(hours=1),
            "recorded_at": start_utc,
            "strain": strain,
            "sport_name": sport_name,
            "kilojoule": kilojoule,
        },
    )
    db.commit()
    return obj


def make_air_reading(
    db: Session,
    *,
    recorded_at: datetime,
    eco2: float | None = 800.0,
    temp: float | None = 19.0,
    humidity: float | None = 45.0,
    tvoc: float | None = 120.0,
    device_id: str = "sense-test",
    external_id: str | None = None,
    source: str = MILL,
) -> AirQualityReading:
    """One polled air-quality snapshot."""
    obj, _ = upsert(
        db,
        AirQualityReading,
        source=source,
        source_external_id=external_id or _unique("air"),
        values={
            "recorded_at": _stored(recorded_at),
            "device_id": device_id,
            "eco2_ppm": eco2,
            "temp_c": temp,
            "humidity_pct": humidity,
            "tvoc_ppb": tvoc,
        },
    )
    db.commit()
    return obj
