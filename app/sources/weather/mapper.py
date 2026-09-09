"""Open-Meteo payload → canonical `weather_daily` values.

Parsing is deliberately defensive and per-day. A weather API is a free public service with
no contract to us: a truncated array or one unparseable date must cost that one day, not the
whole sync — otherwise a single bad row can stall the cursor forever and silently freeze the
source. Every skip is reported back so it lands in `SyncResult.notes` instead of vanishing.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

#: Open-Meteo daily field → `weather_daily` column, for the plain numeric metrics.
METRIC_COLUMNS = {
    "temperature_2m_min": "temp_min_c",
    "temperature_2m_max": "temp_max_c",
    "precipitation_sum": "precipitation_mm",
}

#: Fields that arrive as local ISO timestamps and are stored as UTC instants.
TIME_COLUMNS = {"sunrise": "sunrise", "sunset": "sunset"}

DAYLIGHT_FIELD = "daylight_duration"


def _at(values: Any, index: int) -> Any:
    """`values[index]`, or None if the payload didn't supply one."""
    if not isinstance(values, list) or index >= len(values):
        return None
    return values[index]


def _float_at(values: Any, index: int) -> float | None:
    value = _at(values, index)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _instant_at(values: Any, index: int, tz: ZoneInfo) -> datetime | None:
    """A local ISO timestamp from the payload, as an aware UTC datetime."""
    value = _at(values, index)
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:  # Open-Meteo renders local wall-clock with `timezone=`
        parsed = parsed.replace(tzinfo=tz)
    return parsed.astimezone(UTC)


def parse_daily(payload: dict, tz: ZoneInfo) -> tuple[list[tuple[date, dict]], list[str]]:
    """Split a daily response into `(date, values)` rows and a list of problems.

    A day is skipped only when it cannot be *placed* (unparseable date) or carries nothing
    usable at all. A day missing one metric still lands, with that column null — partial
    weather is better than no weather, and null already means "unknown" everywhere else.
    """
    daily = payload.get("daily")
    if not isinstance(daily, dict):
        return [], ["payload carried no `daily` object"]

    times = daily.get("time")
    if not isinstance(times, list) or not times:
        return [], ["payload carried no `daily.time` array"]

    rows: list[tuple[date, dict]] = []
    problems: list[str] = []

    for index, raw_date in enumerate(times):
        try:
            day = date.fromisoformat(str(raw_date))
        except ValueError:
            problems.append(f"skipped an entry with an unparseable date {raw_date!r}")
            continue

        values: dict[str, Any] = {
            column: _float_at(daily.get(field), index) for field, column in METRIC_COLUMNS.items()
        }
        for field, column in TIME_COLUMNS.items():
            values[column] = _instant_at(daily.get(field), index, tz)

        seconds = _float_at(daily.get(DAYLIGHT_FIELD), index)
        values["daylight_seconds"] = None if seconds is None else int(round(seconds))

        if all(value is None for value in values.values()):
            problems.append(f"skipped {day.isoformat()}: no usable values in the payload")
            continue

        rows.append((day, values))

    return rows, problems
