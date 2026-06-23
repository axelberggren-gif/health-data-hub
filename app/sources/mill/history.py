"""Best-effort historical extraction for Mill Sense air quality.

The Mill cloud's only known historical endpoint is ``POST
devices/{id}/statistics``, which returns *energy usage* for heaters. Whether it
also yields air-quality history for a sensor is undocumented — but the Mill app
shows history graphs, so the series exists server-side somewhere. Rather than
hard-code a response shape we can't see, this module walks an arbitrary
statistics payload and extracts any timestamped air-quality samples it can
recognize. Run ``GET /mill/diagnose`` to capture the real payload and, if
needed, extend the key/synonym tables below.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta

# Multi-metric item: canonical column -> candidate keys (mirrors lastMetrics).
_METRIC_KEYS: dict[str, tuple[str, ...]] = {
    "temp_c": ("temperature", "temperatureAmbient"),
    "humidity_pct": ("humidity",),
    "tvoc_ppb": ("tvoc",),
    "eco2_ppm": ("eco2",),
    "pm1": ("massPm_10",),
    "pm2_5": ("massPm_25",),
    "pm10": ("massPm_100",),
    "battery_pct": ("batteryPercentage",),
}

# Single-metric item ({value, type/name}): metric name (lowercased) -> column.
_METRIC_NAME_SYNONYMS: dict[str, str] = {
    "temperature": "temp_c",
    "temp": "temp_c",
    "temperatureambient": "temp_c",
    "humidity": "humidity_pct",
    "tvoc": "tvoc_ppb",
    "voc": "tvoc_ppb",
    "eco2": "eco2_ppm",
    "co2": "eco2_ppm",
    "co2eq": "eco2_ppm",
    "battery": "battery_pct",
    "batterypercentage": "battery_pct",
    "pm1": "pm1",
    "pm25": "pm2_5",
    "pm2_5": "pm2_5",
    "pm10": "pm10",
}

_TIME_KEYS = ("startPeriod", "endPeriod", "time", "timestamp", "date", "createdAt")
_NAME_KEYS = ("type", "name", "metric", "metricType", "kind")

# Mill's statistics response groups each metric under its own block:
#   {"temperature": {"items": [{startTimestamp, startPeriod, value, level}, ...],
#                    "now": {...}, "min": {...}, "max": {...}},
#    "humidity": {...}, "eco2": {...}, "tvoc": {...}, "timezone": "..."}
# metric block key -> canonical column.
_STAT_METRICS: dict[str, str] = {
    "temperature": "temp_c",
    "humidity": "humidity_pct",
    "eco2": "eco2_ppm",
    "tvoc": "tvoc_ppb",
    "massPm_10": "pm1",
    "pm1": "pm1",
    "massPm_25": "pm2_5",
    "pm25": "pm2_5",
    "massPm_100": "pm10",
    "pm10": "pm10",
}


def _parse_time(value) -> datetime | None:
    if isinstance(value, bool):  # guard: bools are ints in Python
        return None
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1e12:  # milliseconds
            ts /= 1000.0
        try:
            return datetime.fromtimestamp(ts, tz=UTC)
        except (ValueError, OSError, OverflowError):
            return None
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
        except ValueError:
            return None
    return None


def _time_of(item: dict) -> datetime | None:
    for key in _TIME_KEYS:
        if key in item:
            parsed = _parse_time(item[key])
            if parsed is not None:
                return parsed
    return None


def _multi_metrics_of(item: dict) -> dict:
    out: dict[str, float] = {}
    for column, names in _METRIC_KEYS.items():
        for name in names:
            if item.get(name) is not None:
                out[column] = item[name]
                break
    return out


def _named_metric_of(item: dict) -> tuple[str, float] | None:
    if item.get("value") is None:
        return None
    for key in _NAME_KEYS:
        raw = item.get(key)
        if isinstance(raw, str):
            column = _METRIC_NAME_SYNONYMS.get(raw.strip().lower())
            if column:
                return column, item["value"]
    return None


def iter_history_samples(payload) -> Iterator[tuple[datetime, dict]]:
    """Yield ``(recorded_at, {column: value})`` from an arbitrary payload.

    Recursively finds lists of timestamped dicts and coalesces single-metric
    items that share a timestamp into one reading.
    """
    by_time: dict[datetime, dict] = {}

    def visit(node) -> None:
        if isinstance(node, dict):
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for item in node:
                if isinstance(item, dict):
                    ts = _time_of(item)
                    if ts is not None:
                        metrics = _multi_metrics_of(item)
                        named = _named_metric_of(item)
                        if named:
                            metrics.setdefault(*named)
                        if metrics:
                            by_time.setdefault(ts, {}).update(metrics)
                visit(item)

    visit(payload)
    for ts in sorted(by_time):
        yield ts, by_time[ts]


def parse_statistics(payload) -> Iterator[tuple[datetime, dict]]:
    """Parse Mill's statistics response into per-timestamp readings.

    Walks each metric block's ``items`` (the completed buckets — the partial
    ``now`` bucket and the min/max summaries are intentionally skipped) and
    coalesces metrics that share a bucket start time into one reading. Uses the
    epoch ``startTimestamp`` (ms) as the canonical time, falling back to the ISO
    ``startPeriod``. Buckets flagged ``lostStatisticData`` are dropped.
    """
    if not isinstance(payload, dict):
        return
    by_time: dict[datetime, dict] = {}
    for metric_key, column in _STAT_METRICS.items():
        block = payload.get(metric_key)
        if not isinstance(block, dict):
            continue
        for item in block.get("items") or []:
            if not isinstance(item, dict) or item.get("lostStatisticData"):
                continue
            value = item.get("value")
            if value is None:
                continue
            ts = _parse_time(item.get("startTimestamp")) or _parse_time(item.get("startPeriod"))
            if ts is not None:
                by_time.setdefault(ts, {})[column] = value
    for ts in sorted(by_time):
        yield ts, by_time[ts]


def daterange(start: date, end: date) -> Iterator[date]:
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)
