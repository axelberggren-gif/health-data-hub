"""Trailing baselines and z-scores (tech spec §7) — "what is normal for me lately".

Two rules keep the numbers honest:

1. **Windows exclude the day being judged.** Including today would let a value pull its own
   baseline towards itself, which flattens exactly the anomalies the flags look for.
2. **No z-score without enough history or real spread.** Under 14 samples the mean is not yet
   a baseline, and a zero SD would divide by zero (or, worse, report an infinite anomaly for
   a metric that simply never changed).

The spread is a **population** standard deviation: a window is the complete set of days it
covers, not a sample drawn from a larger pool, and it makes the flag thresholds exact rather
than dependent on a floating-point estimate.
"""

from __future__ import annotations

import statistics
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Baseline, DailySummary, utcnow

#: Trailing windows, in complete days.
WINDOWS = (7, 30, 90)

#: `daily_summary` columns worth a baseline. Adding one here is all it takes to trend it.
BASELINE_METRICS = (
    "hrv_rmssd_ms",
    "resting_hr_bpm",
    "recovery_score",
    "sleep_duration_ms",
    "sleep_performance_pct",
    "respiratory_rate",
    "skin_temp_c",
    "spo2_pct",
    "day_strain",
    "readiness_score",
    "night_eco2_ppm_avg",
    "night_temp_c_avg",
)

#: Fewer samples than this and a z-score is noise dressed up as a signal.
MIN_SAMPLES_FOR_Z = 14

#: A baseline needs at least a pair of days for the spread to mean anything.
MIN_SAMPLES_FOR_BASELINE = 2


def z_score(value: float | None, *, mean: float | None, sd: float | None, n: int) -> float | None:
    """How many SDs `value` sits from its baseline, or `None` if that can't be answered."""
    if value is None or mean is None or sd is None:
        return None
    if n < MIN_SAMPLES_FOR_Z or sd <= 0:
        return None
    return (value - mean) / sd


def window_values(db: Session, metric: str, *, reference: date, window: int) -> list[float]:
    """The metric's values over the `window` complete days *before* `reference`."""
    column = getattr(DailySummary, metric)
    rows = (
        db.execute(
            select(column).where(
                DailySummary.date >= reference - timedelta(days=window),
                DailySummary.date < reference,
                column.is_not(None),
            )
        )
        .scalars()
        .all()
    )
    return [float(value) for value in rows]


def recompute_baselines(db: Session, reference: date) -> int:
    """Recompute every (metric, window) baseline in place. Returns the rows touched.

    Recomputed rather than incrementally updated: the whole point is to be re-derivable, and
    12 metrics × 3 windows over a single-user history is trivial work.
    """
    touched = 0
    for metric in BASELINE_METRICS:
        for window in WINDOWS:
            values = window_values(db, metric, reference=reference, window=window)
            if len(values) < MIN_SAMPLES_FOR_BASELINE:
                continue
            row = db.execute(
                select(Baseline).where(Baseline.metric == metric, Baseline.window == window)
            ).scalar_one_or_none()
            if row is None:
                row = Baseline(metric=metric, window=window)
                db.add(row)
            row.mean = statistics.fmean(values)
            row.sd = statistics.pstdev(values)
            row.n = len(values)
            row.computed_at = utcnow()
            touched += 1
    # `SessionLocal` runs with autoflush off, so flush before returning: the flag rules read
    # these rows back in the same transaction and would otherwise see the pre-update values.
    db.flush()
    return touched


def load_baselines(db: Session) -> dict[tuple[str, int], Baseline]:
    """Every baseline row, keyed by `(metric, window)` for cheap lookup by the flag rules."""
    rows = db.execute(select(Baseline)).scalars().all()
    return {(row.metric, row.window): row for row in rows}
