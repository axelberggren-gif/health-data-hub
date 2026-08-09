"""Shared fixture builders (see docs/specs/TEST_SPEC_V1.md, rule 5).

Every builder commits one canonical row with sensible defaults and returns it, so a test
only has to state the values it actually cares about::

    sleep = make_sleep(db, end=local(2026, 6, 10, 7, 12), performance=80.0)

**Timestamps are Europe/Stockholm local unless you pass an aware datetime.** Use
:func:`local` for readable local wall-clock times and :func:`utc` when a test is
specifically about UTC→local conversion (M1-T04/T05). Everything is stored as UTC, which
is what the real adapters write.

Identity: every builder generates a unique ``source_external_id`` from a per-process
counter unless one is passed, satisfying the house rule about distinct external ids on the
shared temp database.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from itertools import count
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.derived import DERIVED_SOURCE
from app.models import (
    AirQualityReading,
    CycleDay,
    DailySummary,
    RecoveryDaily,
    SleepSession,
    Workout,
)

#: Matches `Settings.home_timezone`'s default — the local calendar the derived layer uses.
HOME_TZ = ZoneInfo("Europe/Stockholm")

HOUR_MS = 3_600_000
SEVEN_HOURS_MS = 7 * HOUR_MS

_ids = count(1)


def _next_id(prefix: str) -> str:
    return f"{prefix}-{next(_ids)}"


def local(
    year: int, month: int, day: int, hour: int = 0, minute: int = 0, second: int = 0
) -> datetime:
    """A Europe/Stockholm wall-clock time as an aware datetime."""
    return datetime(year, month, day, hour, minute, second, tzinfo=HOME_TZ)


def utc(
    year: int, month: int, day: int, hour: int = 0, minute: int = 0, second: int = 0
) -> datetime:
    """A UTC instant as an aware datetime."""
    return datetime(year, month, day, hour, minute, second, tzinfo=UTC)


def _to_utc(value: datetime) -> datetime:
    """Interpret a naive datetime as home-local, then normalise to UTC."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=HOME_TZ)
    return value.astimezone(UTC)


def make_sleep(
    db: Session,
    *,
    end: datetime,
    start: datetime | None = None,
    nap: bool = False,
    performance: float | None = 80.0,
    duration_ms: int | None = None,
    awake_ms: int = 0,
    efficiency: float | None = 90.0,
    respiratory_rate: float | None = 14.5,
    disturbances: int | None = 3,
    debt_ms: int | None = 0,
    source: str = "whoop_api",
    external_id: str | None = None,
) -> SleepSession:
    """A sleep session ending at ``end``.

    ``duration_ms`` is *asleep* time (light + slow-wave + REM); ``total_in_bed_ms`` adds
    ``awake_ms`` on top. Pass ``start`` to pin both ends of the session — the asleep time
    is then derived from that span, so the stage totals stay consistent with it.
    """
    end_utc = _to_utc(end)
    if start is not None:
        start_utc = _to_utc(start)
        in_bed_ms = round((end_utc - start_utc).total_seconds() * 1000)
        if duration_ms is None:
            duration_ms = in_bed_ms - awake_ms
    else:
        duration_ms = SEVEN_HOURS_MS if duration_ms is None else duration_ms
        in_bed_ms = duration_ms + awake_ms
        start_utc = end_utc - timedelta(milliseconds=in_bed_ms)

    rem_ms = duration_ms // 5
    slow_wave_ms = duration_ms // 5
    light_ms = duration_ms - rem_ms - slow_wave_ms

    return _add(
        db,
        SleepSession(
            source=source,
            source_external_id=external_id or _next_id("sleep"),
            recorded_at=start_utc,
            start=start_utc,
            end=end_utc,
            nap=nap,
            sleep_performance_pct=performance,
            sleep_efficiency_pct=efficiency,
            respiratory_rate=respiratory_rate,
            disturbance_count=disturbances,
            sleep_debt_ms=debt_ms,
            total_in_bed_ms=in_bed_ms,
            total_awake_ms=awake_ms,
            total_light_ms=light_ms,
            total_slow_wave_ms=slow_wave_ms,
            total_rem_ms=rem_ms,
            total_no_data_ms=0,
        ),
    )


def make_recovery(
    db: Session,
    *,
    recorded_at: datetime | None = None,
    score: float | None = 60.0,
    sleep_id: str | None = None,
    hrv: float | None = 55.0,
    rhr: float | None = 52.0,
    spo2: float | None = 97.0,
    skin_temp: float | None = 33.5,
    user_calibrating: bool | None = False,
    source: str = "whoop_api",
    external_id: str | None = None,
) -> RecoveryDaily:
    """A recovery row. ``sleep_id`` is a sleep's ``source_external_id`` (D1.3)."""
    return _add(
        db,
        RecoveryDaily(
            source=source,
            source_external_id=external_id or _next_id("recovery"),
            recorded_at=_to_utc(recorded_at) if recorded_at else None,
            sleep_id=sleep_id,
            recovery_score=score,
            hrv_rmssd_ms=hrv,
            resting_hr_bpm=rhr,
            spo2_pct=spo2,
            skin_temp_c=skin_temp,
            user_calibrating=user_calibrating,
        ),
    )


def make_cycle(
    db: Session,
    *,
    start: datetime,
    end: datetime | None = None,
    strain: float | None = 12.4,
    kilojoule: float | None = 9000.0,
    source: str = "whoop_api",
    external_id: str | None = None,
) -> CycleDay:
    """A WHOOP physiological cycle (day strain + energy), attributed by ``start`` (D1.4)."""
    start_utc = _to_utc(start)
    return _add(
        db,
        CycleDay(
            source=source,
            source_external_id=external_id or _next_id("cycle"),
            recorded_at=start_utc,
            start=start_utc,
            end=_to_utc(end) if end else start_utc + timedelta(hours=24),
            strain=strain,
            kilojoule=kilojoule,
        ),
    )


def make_workout(
    db: Session,
    *,
    start: datetime,
    end: datetime | None = None,
    strain: float | None = 8.5,
    sport_name: str | None = "running",
    kilojoule: float | None = 2000.0,
    source: str = "whoop_api",
    external_id: str | None = None,
) -> Workout:
    """A workout, attributed by ``start`` (D1.4)."""
    start_utc = _to_utc(start)
    return _add(
        db,
        Workout(
            source=source,
            source_external_id=external_id or _next_id("workout"),
            recorded_at=start_utc,
            start=start_utc,
            end=_to_utc(end) if end else start_utc + timedelta(hours=1),
            strain=strain,
            sport_name=sport_name,
            kilojoule=kilojoule,
        ),
    )


def make_air_reading(
    db: Session,
    *,
    recorded_at: datetime,
    eco2: float | None = 800.0,
    temp: float | None = 19.0,
    humidity: float | None = 45.0,
    tvoc: float | None = 120.0,
    device_id: str = "mill-test-device",
    source: str = "mill_sense",
    external_id: str | None = None,
) -> AirQualityReading:
    """One indoor-air sample (the Mill poller writes one of these per poll)."""
    return _add(
        db,
        AirQualityReading(
            source=source,
            source_external_id=external_id or _next_id("air"),
            recorded_at=_to_utc(recorded_at),
            device_id=device_id,
            eco2_ppm=eco2,
            temp_c=temp,
            humidity_pct=humidity,
            tvoc_ppb=tvoc,
        ),
    )


def make_summary(db: Session, *, day: date, **values: Any) -> DailySummary:
    """A `daily_summary` row written directly, for baseline / flag / statistics tests.

    Deliberately bypasses the derivation job: those tests need long synthetic histories
    with *known* values, not fixtures for every upstream table on every one of 90 days.
    """
    return _add(
        db,
        DailySummary(source=DERIVED_SOURCE, source_external_id=day.isoformat(), date=day, **values),
    )


def _add(db: Session, obj: Any) -> Any:
    db.add(obj)
    db.commit()
    return obj
