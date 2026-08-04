"""Day attribution: which local calendar date does a canonical row belong to?

Every derived table is keyed on a **local** date, so the rollup layer needs one
unambiguous answer per row type. The rules are TECH_SPEC_V1 §3 D1:

* the local calendar is ``Settings.home_timezone`` (IANA name);
* **sleep** attributes to its *wake* date — the local date of ``end`` — and naps
  (``nap == True``) never count as the night's sleep;
* **recovery** attributes to the wake date of its linked sleep when that link
  resolves, else to the local date of ``recorded_at``;
* **cycles and workouts** attribute to the local date of ``start`` (so a workout
  that starts 23:50 and ends after midnight belongs to the day it started);
* the **night window** for a date is that night's sleep ``start``–``end``, used
  to aggregate air-quality readings actually breathed while asleep.

Everything here is a pure function of its arguments (the DB-reading helpers are
pure with respect to the store — they never write). Per-record
``timezone_offset`` strings are deliberately ignored in V1: one user, one home
zone (D1.6).

**Naive datetimes are treated as UTC.** SQLAlchemy's SQLite dialect stores
``DateTime(timezone=True)`` values as a naive wall-clock string and hands them
back without a ``tzinfo``, so a row round-tripped through SQLite loses its
offset. Since the store only ever holds UTC instants, reading a naive value back
as UTC restores the original instant; on Postgres the value arrives aware and is
converted rather than assumed.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import RecoveryDaily, SleepSession


def home_timezone() -> str:
    """The configured local calendar (default ``Europe/Stockholm``)."""
    return get_settings().home_timezone


def as_utc(moment: datetime) -> datetime:
    """Return ``moment`` as an aware UTC datetime, reading naive input as UTC."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


def local_date(moment: datetime, tz: str | None = None) -> date:
    """The local calendar date of an instant, in ``tz`` (default: home zone).

    This is a timezone *conversion*, not UTC bucketing: 2026-06-09 23:30 UTC is
    01:30 on 2026-06-10 in Europe/Stockholm, so the date is the 10th.
    """
    zone = ZoneInfo(tz or home_timezone())
    return as_utc(moment).astimezone(zone).date()


def sleep_wake_date(end_utc: datetime, tz: str | None = None) -> date:
    """The date a sleep session is attributed to: the local date it ended (D1.2)."""
    return local_date(end_utc, tz)


def event_local_date(start_utc: datetime, tz: str | None = None) -> date:
    """The date a workout or cycle is attributed to: the local date it started (D1.4)."""
    return local_date(start_utc, tz)


def _local_day_bounds_utc(day: date, tz: str | None = None) -> tuple[datetime, datetime]:
    """The UTC instants bracketing a local calendar day: ``[start, next start)``.

    Built from local midnight so DST transitions shorten or lengthen the day
    correctly instead of assuming every day is 24 h long.
    """
    zone = ZoneInfo(tz or home_timezone())
    start_local = datetime.combine(day, datetime.min.time(), tzinfo=zone)
    end_local = datetime.combine(day + timedelta(days=1), datetime.min.time(), tzinfo=zone)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


def _duration(session: SleepSession) -> timedelta:
    if session.start is None or session.end is None:
        return timedelta(0)
    return as_utc(session.end) - as_utc(session.start)


def night_sleep_for_date(db: Session, day: date, tz: str | None = None) -> SleepSession | None:
    """The main *night* sleep attributed to ``day``, or ``None``.

    Naps are excluded (D1.2) — a date with only a nap has no night sleep. When
    several night sessions share a wake date (a fragmented night) the longest
    one wins, tie-broken by the later ``end``, so the choice is deterministic.
    """
    start_utc, end_utc = _local_day_bounds_utc(day, tz)
    candidates = (
        db.execute(
            select(SleepSession).where(
                SleepSession.end >= start_utc,
                SleepSession.end < end_utc,
                or_(SleepSession.nap.is_(None), SleepSession.nap.is_(False)),
            )
        )
        .scalars()
        .all()
    )
    if not candidates:
        return None
    return max(candidates, key=lambda s: (_duration(s), as_utc(s.end) if s.end else start_utc))


def attribute_recovery(recovery: RecoveryDaily, db: Session, tz: str | None = None) -> date | None:
    """The date a recovery row is attributed to (D1.3).

    The wake date of the sleep it references, when that reference resolves;
    otherwise the local date of ``recorded_at``. ``None`` only when neither is
    available — the caller skips such a row rather than inventing a day.
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


def night_window(db: Session, day: date, tz: str | None = None) -> tuple[datetime, datetime] | None:
    """The UTC ``(start, end)`` of ``day``'s night sleep, or ``None`` (D1.5a).

    Callers aggregate air-quality readings inside this window — the air actually
    breathed while asleep, which is what readiness's environment component uses.
    No night sleep for the date means no window, and therefore no night-air
    aggregate (never a silent fallback to the whole calendar day).
    """
    sleep = night_sleep_for_date(db, day, tz)
    if sleep is None or sleep.start is None or sleep.end is None:
        return None
    return as_utc(sleep.start), as_utc(sleep.end)
