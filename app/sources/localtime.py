"""Local-calendar helpers shared by the source adapters.

`app/derived/dates.py` has richer versions of these, but the layering forbids a source from
importing the derived layer (a source must not depend on a consumer). These two helpers are
the small part every date-keyed adapter needs: which zone "local" means, and the UTC instant
a local date begins — which is the stable `recorded_at` for a row keyed by a date rather
than by a moment.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from ..config import get_settings


def home_tz() -> ZoneInfo:
    """The local calendar every date key is bucketed by (`Settings.home_timezone`, D1)."""
    return ZoneInfo(get_settings().home_timezone)


def local_midnight_utc(day: date) -> datetime:
    """The instant a local date starts, as an aware UTC datetime."""
    return datetime.combine(day, time.min, tzinfo=home_tz()).astimezone(UTC)
