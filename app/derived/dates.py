"""Day attribution — which local date each canonical row belongs to.

Every derived table is keyed by a **local calendar date** in `Settings.home_timezone`, so
this module is the foundation the whole derived layer stands on. The rules come from tech
spec D1 and are deliberately boring and explicit:

- **Sleep** attributes to the **wake date** — the local date of `end`. Naps are excluded from
  the nightly selector (they still exist for the day-timeline view).
- **Recovery** attributes to the wake date of its linked sleep when that link resolves, and
  otherwise to the local date of `recorded_at`.
- **Workouts and cycles** attribute to the local date they **start**, even when they end the
  next day.
- The **night window** for a date is that night's sleep `start`..`end`, used to aggregate the
  air readings that were actually breathed during the night.

**Storage contract.** Canonical timestamps are stored in UTC (that is what the source mappers
produce). SQLite discards the offset, so values read back are *naive UTC* — every function
here normalizes with `as_utc()` before converting, and a naive datetime is always read as UTC,
never as local time. Getting that backwards shifts a whole night onto the wrong date.

Per-record `timezone_offset` values are intentionally ignored in V1: one user, one home zone.
Travel-aware attribution is a later pass (tech spec §15).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import RecoveryDaily, SleepSession


def home_tz() -> ZoneInfo:
    """The configured home timezone (`Settings.home_timezone`)."""
    return ZoneInfo(get_settings().home_timezone)


def as_utc(moment: datetime) -> datetime:
    """Make an instant timezone-aware in UTC — a naive value is *already* UTC."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


def local_date(moment: datetime, tz: ZoneInfo | None = None) -> date:
    """The local calendar date an instant falls on."""
    return as_utc(moment).astimezone(tz or home_tz()).date()


def sleep_wake_date(end: datetime, tz: ZoneInfo | None = None) -> date:
    """D1.2 — a night belongs to the day you woke up on."""
    return local_date(end, tz)


def event_local_date(start: datetime, tz: ZoneInfo | None = None) -> date:
    """D1.4 — workouts and cycles belong to the local date they start."""
    return local_date(start, tz)


def day_bounds_utc(day: date, tz: ZoneInfo | None = None) -> tuple[datetime, datetime]:
    """The UTC instants a local date starts and ends at (end exclusive)."""
    tz = tz or home_tz()
    start = datetime.combine(day, time.min, tzinfo=tz)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz)
    return start.astimezone(UTC), end.astimezone(UTC)


def night_sleep_for_date(db: Session, day: date, tz: ZoneInfo | None = None) -> SleepSession | None:
    """The main (non-nap) sleep whose wake date is `day`, or `None`.

    A night can only end within the 24 hours of the local date it is attributed to, so the
    query is bounded by that date's UTC span and the exact local-date test is applied in
    Python (the boundary is a timezone conversion, not something SQL can express portably).
    When more than one non-nap session ends on the same date, the longest one is the night.
    """
    tz = tz or home_tz()
    start_utc, end_utc = day_bounds_utc(day, tz)

    candidates = (
        db.execute(
            select(SleepSession).where(
                SleepSession.end.is_not(None),
                SleepSession.end >= start_utc,
                SleepSession.end < end_utc,
            )
        )
        .scalars()
        .all()
    )

    nights = [
        sleep
        for sleep in candidates
        if not sleep.nap and sleep.end is not None and sleep_wake_date(sleep.end, tz) == day
    ]
    if not nights:
        return None
    return max(nights, key=_duration)


def _duration(sleep: SleepSession) -> timedelta:
    if sleep.start is None or sleep.end is None:
        return timedelta(0)
    return as_utc(sleep.end) - as_utc(sleep.start)


def night_window(
    db: Session, day: date, tz: ZoneInfo | None = None
) -> tuple[datetime, datetime] | None:
    """D1.5a — the UTC `(start, end)` of `day`'s night, or `None` if there was no sleep.

    Both ends are inclusive for the readings that fall on them: a sample taken exactly at
    lights-out or at wake-up was still part of that night.
    """
    sleep = night_sleep_for_date(db, day, tz)
    if sleep is None or sleep.start is None or sleep.end is None:
        return None
    return as_utc(sleep.start), as_utc(sleep.end)


def attribute_recovery(
    recovery: RecoveryDaily, db: Session, tz: ZoneInfo | None = None
) -> date | None:
    """D1.3 — the date a recovery score belongs to.

    Prefers the wake date of the sleep it scores (`sleep_id` -> that sleep's
    `source_external_id`); falls back to the local date of `recorded_at` when the link is
    absent or dangling. Returns `None` only when neither is available.
    """
    if recovery.sleep_id:
        sleep = (
            db.execute(
                select(SleepSession).where(
                    SleepSession.source == recovery.source,
                    SleepSession.source_external_id == recovery.sleep_id,
                )
            )
            .scalars()
            .first()
        )
        if sleep is not None and sleep.end is not None:
            return sleep_wake_date(sleep.end, tz)

    if recovery.recorded_at is not None:
        return local_date(recovery.recorded_at, tz)
    return None
