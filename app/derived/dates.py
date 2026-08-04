"""Day attribution — which local day (or night) a canonical row belongs to.

This is decision **D1** of the V1 tech spec in code. Everything downstream keys off a
*local* date in `Settings.home_timezone`, and each row type has its own rule:

* **sleep** → the local date it *ends* on (the wake date); naps are not nights
* **recovery** → the wake date of its linked sleep, else the local date of `recorded_at`
* **workouts / cycles** → the local date they *start* on
* **air readings** → the night window (the night's sleep span) they fall inside

Two traps this module exists to avoid:

1. **Never bucket by the UTC date.** A sleep ending 23:30 UTC belongs to the *next* local
   day in Stockholm. Conversion happens through `zoneinfo`, which also makes the DST
   transitions correct for free.
2. **SQLite gives back naive datetimes** even for `DateTime(timezone=True)` columns. Values
   are stored as UTC, so anything naive is treated as UTC on the way in.

Per-record `timezone_offset` strings are deliberately ignored here (D1.6): V1 is one user
in one home zone. Travel-aware attribution is a later pass and would start in this module.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import AirQualityReading, RecoveryDaily, SleepSession


def home_tz() -> ZoneInfo:
    """The configured home timezone — the calendar every derived `date` key uses."""
    return ZoneInfo(get_settings().home_timezone)


def as_utc(value: datetime) -> datetime:
    """Make a stored timestamp aware. Naive values are UTC (that is how we store them)."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def local_date(value: datetime, tz: ZoneInfo | None = None) -> date:
    """The local calendar date of an instant."""
    return as_utc(value).astimezone(tz or home_tz()).date()


def sleep_wake_date(end: datetime, tz: ZoneInfo | None = None) -> date:
    """D1.2 — a sleep belongs to the local date it ends on."""
    return local_date(end, tz)


def event_local_date(start: datetime, tz: ZoneInfo | None = None) -> date:
    """D1.4 — workouts and cycles belong to the local date they start on."""
    return local_date(start, tz)


def day_bounds(day: date, tz: ZoneInfo | None = None) -> tuple[datetime, datetime]:
    """The UTC instants bracketing a local date, as `[start, end)`."""
    zone = tz or home_tz()
    start = datetime.combine(day, time.min, tzinfo=zone)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=zone)
    return start.astimezone(UTC), end.astimezone(UTC)


def night_sleep_for_date(
    db: Session, day: date, tz: ZoneInfo | None = None
) -> SleepSession | None:
    """The night's main sleep for a local date, or `None`.

    Naps are excluded (D1.2), so a day with only a nap has no night sleep. If several
    non-nap sessions wake on the same date (a fragmented night), the longest one is the
    main sleep and the rest are ignored for rollups.
    """
    start, end = day_bounds(day, tz)
    candidates = (
        db.execute(
            select(SleepSession).where(
                SleepSession.end.is_not(None),
                SleepSession.end >= start,
                SleepSession.end < end,
                SleepSession.nap.is_not(True),
            )
        )
        .scalars()
        .all()
    )
    if not candidates:
        return None
    return max(candidates, key=lambda s: (s.total_in_bed_ms or 0, s.id))


def night_window(
    db: Session, day: date, tz: ZoneInfo | None = None
) -> tuple[datetime, datetime] | None:
    """D1.5a — the `[start, end]` span of the night's sleep, or `None` if there was none.

    This is the window that feeds readiness: "what was the air like *while I slept*",
    which is a different question from "what was the air like on this calendar day".
    """
    sleep = night_sleep_for_date(db, day, tz)
    if sleep is None or sleep.start is None or sleep.end is None:
        return None
    return as_utc(sleep.start), as_utc(sleep.end)


def night_air_readings(
    db: Session, day: date, tz: ZoneInfo | None = None
) -> list[AirQualityReading]:
    """Air readings taken during the night attributed to `day` (empty if no sleep)."""
    window = night_window(db, day, tz)
    if window is None:
        return []
    start, end = window
    return list(
        db.execute(
            select(AirQualityReading)
            .where(
                AirQualityReading.recorded_at.is_not(None),
                AirQualityReading.recorded_at >= start,
                AirQualityReading.recorded_at <= end,
            )
            .order_by(AirQualityReading.recorded_at)
        )
        .scalars()
        .all()
    )


def attribute_recovery(
    db: Session, recovery: RecoveryDaily, tz: ZoneInfo | None = None
) -> date | None:
    """D1.3 — the local date a recovery describes.

    WHOOP computes recovery from the night's sleep, so the sleep's wake date is the
    truthful key. `recorded_at` (when WHOOP created the record) is the fallback for rows
    whose `sleep_id` is missing or points at a sleep we have not synced.
    """
    if recovery.sleep_id:
        sleep = db.execute(
            select(SleepSession).where(
                SleepSession.source == recovery.source,
                SleepSession.source_external_id == recovery.sleep_id,
            )
        ).scalar_one_or_none()
        if sleep is not None and sleep.end is not None:
            return sleep_wake_date(sleep.end, tz)
    if recovery.recorded_at is None:
        return None
    return local_date(recovery.recorded_at, tz)
