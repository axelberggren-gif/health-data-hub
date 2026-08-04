"""Canonical rows → one `daily_summary` row per local date (tech spec §5.1).

The aggregation helpers are pure (`rows -> values`) so they can be tested against golden
fixtures without a database, and `summarize_date` is the only part that queries.

`summarize_date` returns `None` for a date with no upstream data at all. That is deliberate:
a day the owner did not wear the strap has no summary rather than a row of nulls, so "no
data" and "measured nothing" stay distinguishable, and a wide `days_back` cannot manufacture
years of empty rows.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AirQualityReading, CycleDay, RecoveryDaily, SleepSession, Workout
from .dates import (
    attribute_recovery,
    day_bounds,
    event_local_date,
    home_tz,
    night_air_readings,
    night_sleep_for_date,
)
from .readiness import air_score, compute_readiness

#: Recovery, cycle and workout rows are attributed by *converting* a timestamp, not by a
#: stored date, so candidate queries widen the local day by a margin that comfortably covers
#: any timezone offset and lets the attribution rule make the actual decision.
_ATTRIBUTION_SLACK = timedelta(hours=36)

#: The `daily_summary` columns each group owns. Naming them keeps "a day with no recovery" and
#: "a day whose recovery was never recomputed" from looking the same in the database.
RECOVERY_COLUMNS = (
    "recovery_score",
    "hrv_rmssd_ms",
    "resting_hr_bpm",
    "spo2_pct",
    "skin_temp_c",
)
SLEEP_COLUMNS = (
    "sleep_performance_pct",
    "sleep_efficiency_pct",
    "sleep_duration_ms",
    "sleep_debt_ms",
    "rem_ms",
    "slow_wave_ms",
    "respiratory_rate",
    "disturbance_count",
)
AIR_COLUMNS = (
    "night_temp_c_avg",
    "night_eco2_ppm_avg",
    "night_eco2_ppm_max",
    "night_tvoc_ppb_avg",
    "night_humidity_pct_avg",
)


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _present(values: list[float | None]) -> list[float]:
    return [v for v in values if v is not None]


def recovery_values(recovery: RecoveryDaily | None) -> dict[str, Any]:
    """The recovery columns of a daily summary.

    Every column is always returned, `None` when there is no recovery, so that a recomputed
    row is a pure function of its inputs. Omitting keys instead would leave `upsert()`
    carrying yesterday's values forward if a record is later corrected onto another day.
    """
    if recovery is None:
        return dict.fromkeys(RECOVERY_COLUMNS)
    return {
        "recovery_score": recovery.recovery_score,
        "hrv_rmssd_ms": recovery.hrv_rmssd_ms,
        "resting_hr_bpm": recovery.resting_hr_bpm,
        "spo2_pct": recovery.spo2_pct,
        "skin_temp_c": recovery.skin_temp_c,
    }


def sleep_values(sleep: SleepSession | None) -> dict[str, Any]:
    """The sleep columns of a daily summary.

    `sleep_duration_ms` is time *asleep* (light + slow-wave + REM) when the stage totals are
    present, falling back to time in bed minus awake and no-data time. Both readings of "how
    much did I sleep" exclude lying awake, which is the number worth trending.

    Always returns every column (see `recovery_values`).
    """
    if sleep is None:
        return dict.fromkeys(SLEEP_COLUMNS)

    stages = _present([sleep.total_light_ms, sleep.total_slow_wave_ms, sleep.total_rem_ms])
    if stages:
        duration_ms: int | None = int(sum(stages))
    elif sleep.total_in_bed_ms is not None:
        duration_ms = (
            sleep.total_in_bed_ms - (sleep.total_awake_ms or 0) - (sleep.total_no_data_ms or 0)
        )
    else:
        duration_ms = None

    return {
        "sleep_performance_pct": sleep.sleep_performance_pct,
        "sleep_efficiency_pct": sleep.sleep_efficiency_pct,
        "sleep_duration_ms": duration_ms,
        "sleep_debt_ms": sleep.sleep_debt_ms,
        "rem_ms": sleep.total_rem_ms,
        "slow_wave_ms": sleep.total_slow_wave_ms,
        "respiratory_rate": sleep.respiratory_rate,
        "disturbance_count": sleep.disturbance_count,
    }


def strain_values(cycle: CycleDay | None, workouts: list[Workout]) -> dict[str, Any]:
    """The strain / training-load columns. `workout_count` is 0, not null, on a rest day."""
    strains = _present([w.strain for w in workouts])
    return {
        "day_strain": cycle.strain if cycle else None,
        "kilojoule": cycle.kilojoule if cycle else None,
        "workout_count": len(workouts),
        "workout_strain_sum": sum(strains) if strains else None,
    }


def air_values(readings: list[AirQualityReading]) -> dict[str, Any]:
    """Night-window air aggregates (D1.5a) — averages, plus the peak CO2 of the night.

    Always returns every column (see `recovery_values`).
    """
    if not readings:
        return dict.fromkeys(AIR_COLUMNS)
    eco2 = _present([r.eco2_ppm for r in readings])
    return {
        "night_temp_c_avg": _mean(_present([r.temp_c for r in readings])),
        "night_eco2_ppm_avg": _mean(eco2),
        "night_eco2_ppm_max": max(eco2) if eco2 else None,
        "night_tvoc_ppb_avg": _mean(_present([r.tvoc_ppb for r in readings])),
        "night_humidity_pct_avg": _mean(_present([r.humidity_pct for r in readings])),
    }


def _recovery_for_date(
    db: Session, day: date, tz: ZoneInfo, sleep: SleepSession | None
) -> RecoveryDaily | None:
    """The recovery attributed to `day` (D1.3).

    The direct route is the link WHOOP already gives us: the night's sleep id. Only if that
    finds nothing does this fall back to scanning a window around the date and attributing
    candidates one by one — which is also the path for rows with no `sleep_id` at all.
    """
    if sleep is not None:
        linked = db.execute(
            select(RecoveryDaily).where(
                RecoveryDaily.source == sleep.source,
                RecoveryDaily.sleep_id == sleep.source_external_id,
            )
        ).scalar_one_or_none()
        if linked is not None:
            return linked

    start, end = day_bounds(day, tz)
    candidates = (
        db.execute(
            select(RecoveryDaily)
            .where(
                RecoveryDaily.recorded_at.is_not(None),
                RecoveryDaily.recorded_at >= start - _ATTRIBUTION_SLACK,
                RecoveryDaily.recorded_at <= end + _ATTRIBUTION_SLACK,
            )
            .order_by(RecoveryDaily.recorded_at)
        )
        .scalars()
        .all()
    )
    for recovery in candidates:
        if attribute_recovery(db, recovery, tz) == day:
            return recovery
    return None


def _cycle_for_date(db: Session, day: date, tz: ZoneInfo) -> CycleDay | None:
    """The cycle starting on `day` (D1.4); the longest one if WHOOP split the day."""
    cycles = _rows_starting_on(db, CycleDay, day, tz)
    if not cycles:
        return None
    return max(cycles, key=lambda c: (c.strain or 0.0, c.id))


def _rows_starting_on(db: Session, model: Any, day: date, tz: ZoneInfo) -> list[Any]:
    start, end = day_bounds(day, tz)
    rows = (
        db.execute(
            select(model).where(
                model.start.is_not(None),
                model.start >= start - _ATTRIBUTION_SLACK,
                model.start <= end + _ATTRIBUTION_SLACK,
            )
        )
        .scalars()
        .all()
    )
    return [row for row in rows if event_local_date(row.start, tz) == day]


def summarize_date(db: Session, day: date, tz: ZoneInfo | None = None) -> dict[str, Any] | None:
    """Everything known about one local date, or `None` if nothing is."""
    zone = tz or home_tz()

    sleep = night_sleep_for_date(db, day, zone)
    recovery = _recovery_for_date(db, day, zone, sleep)
    cycle = _cycle_for_date(db, day, zone)
    workouts = _rows_starting_on(db, Workout, day, zone)
    readings = night_air_readings(db, day, zone)

    if recovery is None and sleep is None and cycle is None and not workouts and not readings:
        return None

    values: dict[str, Any] = {}
    values.update(recovery_values(recovery))
    values.update(sleep_values(sleep))
    values.update(strain_values(cycle, workouts))
    values.update(air_values(readings))

    readiness, components = compute_readiness(
        recovery_score=values.get("recovery_score"),
        user_calibrating=recovery.user_calibrating if recovery else None,
        sleep_performance_pct=values.get("sleep_performance_pct"),
        environment_score=air_score(
            values.get("night_eco2_ppm_avg"),
            values.get("night_temp_c_avg"),
            values.get("night_humidity_pct_avg"),
        ),
    )
    values["readiness_score"] = readiness
    values["readiness_components"] = components
    return values
