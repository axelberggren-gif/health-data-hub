"""Shared fixture builders for the canonical tables (TEST_SPEC_V1.md rule 5).

Every builder returns a **committed** ORM row written through
``app.sync.orchestrator.upsert()`` — house invariant #2 (never a raw ``db.add()``
that a re-run could duplicate). Defaults are sensible; everything is overridable
by keyword, and unknown keywords are passed straight through to the model columns
via ``**extra`` so later milestones can extend a fixture without editing it here.

Timestamps
----------
Per TEST_SPEC rule 5, times in the catalog are **Europe/Stockholm local** unless
suffixed ``UTC``. Use :func:`local` and :func:`utc` so a test reads like the
catalog entry it implements::

    make_sleep(db, start=local(2026, 6, 9, 23, 0), end=local(2026, 6, 10, 7, 0))
    make_sleep(db, end=utc(2026, 6, 9, 23, 30))          # 01:30 local CEST

Whatever you hand a builder — aware (any zone) or naive — is normalised to UTC
before it is stored, because SQLAlchemy's SQLite dialect silently drops ``tzinfo``
and would otherwise persist a *local wall clock* as if it were UTC. Rows therefore
always read back as naive UTC; :func:`as_utc` turns such a value (or an aware one
in any zone) back into an aware UTC datetime.

Identity
--------
The whole suite shares one temp SQLite file, so ``source_external_id`` must be
unique per row. Builders auto-generate one from a module-level ``itertools.count``
(deterministic, no ``uuid4``/random/clock). Tests that query the store should pass
an explicit, test-prefixed id instead (e.g. ``"m1t08-air-2330"``) so a failure is
traceable and queries can be scoped to that prefix.
"""

from __future__ import annotations

import itertools
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.models import AirQualityReading, CycleDay, RecoveryDaily, SleepSession, Workout
from app.sync.orchestrator import upsert

#: The home zone the derived layer buckets days in (mirrors ``Settings.home_timezone``).
HOME_TZ = "Europe/Stockholm"

#: Source names the canonical rows are attributed to.
WHOOP_SOURCE = "whoop_api"
MILL_SOURCE = "mill_sense"

_ID_COUNTER = itertools.count(1)


def _auto_id(prefix: str) -> str:
    """A unique, deterministic ``source_external_id`` (no randomness, no clock)."""
    return f"{prefix}-{next(_ID_COUNTER)}"


# --------------------------------------------------------------------------
# Datetime helpers
# --------------------------------------------------------------------------
def local(y: int, m: int, d: int, h: int = 0, minute: int = 0, *, tz: str = HOME_TZ) -> datetime:
    """An aware datetime for a **local** wall clock in the home zone."""
    return datetime(y, m, d, h, minute, tzinfo=ZoneInfo(tz))


def utc(y: int, m: int, d: int, h: int = 0, minute: int = 0) -> datetime:
    """An aware datetime in **UTC** (for the catalog's ``… UTC`` timestamps)."""
    return datetime(y, m, d, h, minute, tzinfo=UTC)


def as_utc(value: datetime) -> datetime:
    """Normalise to an aware UTC datetime; a naive value is *read as* UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


# --------------------------------------------------------------------------
# Canonical row builders
# --------------------------------------------------------------------------
def make_sleep(
    db: Session,
    *,
    end: datetime,
    start: datetime | None = None,
    nap: bool = False,
    performance: float = 80.0,
    source_external_id: str | None = None,
    **extra: Any,
) -> SleepSession:
    """A ``SleepSession``. ``start`` defaults to eight hours before ``end``."""
    end_utc = as_utc(end)
    start_utc = as_utc(start) if start is not None else end_utc - timedelta(hours=8)
    values: dict[str, Any] = {
        "start": start_utc,
        "end": end_utc,
        "nap": nap,
        "sleep_performance_pct": performance,
        "recorded_at": end_utc,
    }
    values.update(extra)
    obj, _ = upsert(
        db,
        SleepSession,
        source=WHOOP_SOURCE,
        source_external_id=source_external_id or _auto_id("fx-sleep"),
        values=values,
    )
    db.commit()
    return cast(SleepSession, obj)


def make_recovery(
    db: Session,
    *,
    score: float = 60.0,
    sleep_id: str | None = None,
    hrv: float = 55.0,
    rhr: float = 52.0,
    recorded_at: datetime | None = None,
    source_external_id: str | None = None,
    **extra: Any,
) -> RecoveryDaily:
    """A ``RecoveryDaily``.

    ``sleep_id`` is WHOOP's link to a sleep session and is matched against
    ``SleepSession.source_external_id`` (tech spec D1.3). ``recorded_at`` is
    stored as given — left ``None`` when not passed, so a test that relies on the
    ``recorded_at`` fallback has to say so explicitly.
    """
    values: dict[str, Any] = {
        "recovery_score": score,
        "sleep_id": sleep_id,
        "hrv_rmssd_ms": hrv,
        "resting_hr_bpm": rhr,
        "recorded_at": as_utc(recorded_at) if recorded_at is not None else None,
    }
    values.update(extra)
    obj, _ = upsert(
        db,
        RecoveryDaily,
        source=WHOOP_SOURCE,
        source_external_id=source_external_id or _auto_id("fx-recovery"),
        values=values,
    )
    db.commit()
    return cast(RecoveryDaily, obj)


def make_cycle(
    db: Session,
    *,
    start: datetime,
    strain: float = 12.4,
    end: datetime | None = None,
    source_external_id: str | None = None,
    **extra: Any,
) -> CycleDay:
    """A ``CycleDay`` (WHOOP's ~24h physiological cycle). ``end`` defaults to ``start`` + 24h."""
    start_utc = as_utc(start)
    values: dict[str, Any] = {
        "start": start_utc,
        "end": as_utc(end) if end is not None else start_utc + timedelta(hours=24),
        "strain": strain,
        "recorded_at": start_utc,
    }
    values.update(extra)
    obj, _ = upsert(
        db,
        CycleDay,
        source=WHOOP_SOURCE,
        source_external_id=source_external_id or _auto_id("fx-cycle"),
        values=values,
    )
    db.commit()
    return cast(CycleDay, obj)


def make_workout(
    db: Session,
    *,
    start: datetime,
    end: datetime | None = None,
    strain: float = 8.0,
    source_external_id: str | None = None,
    **extra: Any,
) -> Workout:
    """A ``Workout``. ``end`` defaults to one hour after ``start``."""
    start_utc = as_utc(start)
    values: dict[str, Any] = {
        "start": start_utc,
        "end": as_utc(end) if end is not None else start_utc + timedelta(hours=1),
        "strain": strain,
        "recorded_at": start_utc,
    }
    values.update(extra)
    obj, _ = upsert(
        db,
        Workout,
        source=WHOOP_SOURCE,
        source_external_id=source_external_id or _auto_id("fx-workout"),
        values=values,
    )
    db.commit()
    return cast(Workout, obj)


def make_air_reading(
    db: Session,
    *,
    recorded_at: datetime,
    eco2: float = 800.0,
    temp: float = 19.0,
    humidity: float = 45.0,
    tvoc: float = 100.0,
    source_external_id: str | None = None,
    **extra: Any,
) -> AirQualityReading:
    """An ``AirQualityReading`` from the Mill Sense sensor (one poll = one row)."""
    values: dict[str, Any] = {
        "recorded_at": as_utc(recorded_at),
        "device_id": "fx-device",
        "device_name": "Fixture Sense",
        "eco2_ppm": eco2,
        "temp_c": temp,
        "humidity_pct": humidity,
        "tvoc_ppb": tvoc,
    }
    values.update(extra)
    obj, _ = upsert(
        db,
        AirQualityReading,
        source=MILL_SOURCE,
        source_external_id=source_external_id or _auto_id("fx-air"),
        values=values,
    )
    db.commit()
    return cast(AirQualityReading, obj)
