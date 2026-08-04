"""Trailing baselines and z-scores (see docs/specs/TEST_SPEC_V1.md, M2 — tech spec §7).

A baseline is "what is normal for me lately" over the trailing 7 / 30 / 90 complete days.
It must **exclude the day being judged**, otherwise today's value pulls its own baseline
towards itself and every anomaly threshold drifts.

The expected values here are hand-computed, not snapshotted: the fixture HRV series is a
ramp of consecutive integers, so the mean of any window is its midpoint and the population
standard deviation of *k* consecutive integers is the closed form `sqrt((k² - 1) / 12)`.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

import pytest

from app.derived.baselines import recompute_baselines, z_score
from app.models import Baseline
from tests.factories import make_summary

REFERENCE = date(2026, 6, 30)
HISTORY_DAYS = 40


def _consecutive_sd(k: int) -> float:
    """Population SD of k consecutive integers."""
    return math.sqrt((k * k - 1) / 12)


@pytest.fixture
def hrv_history(clean_db):
    """40 daily summaries ending on REFERENCE, HRV ramping 40, 41, … 79."""
    for offset in range(HISTORY_DAYS - 1, -1, -1):
        day = REFERENCE - timedelta(days=offset)
        make_summary(clean_db, day=day, hrv_rmssd_ms=float(40 + (HISTORY_DAYS - 1 - offset)))
    return clean_db


def _baseline(db, metric: str, window: int) -> Baseline:
    return (
        db.query(Baseline).filter(Baseline.metric == metric, Baseline.window == window).one()
    )


@pytest.mark.parametrize(
    ("window", "expected_n", "expected_mean"),
    [
        (7, 7, 75.0),  # HRV 72 … 78 (the seven days before REFERENCE)
        (30, 30, 63.5),  # HRV 49 … 78
        (90, 39, 59.0),  # only 39 complete days exist -> HRV 40 … 78
    ],
)
def test_baseline_windows(
    hrv_history, window: int, expected_n: int, expected_mean: float
) -> None:
    """M2-T07: each window's mean / SD / n match the hand-computed values."""
    recompute_baselines(hrv_history, REFERENCE)

    row = _baseline(hrv_history, "hrv_rmssd_ms", window)
    assert row.n == expected_n
    assert row.mean == pytest.approx(expected_mean)
    assert row.sd == pytest.approx(_consecutive_sd(expected_n))


def test_baselines_exclude_the_day_being_judged(hrv_history) -> None:
    """M2-T07: REFERENCE's own value (79) is not in any window."""
    recompute_baselines(hrv_history, REFERENCE)

    # Including day 79 would lift the 7-day mean from 75.0 to 76.0.
    assert _baseline(hrv_history, "hrv_rmssd_ms", 7).mean == pytest.approx(75.0)
    assert _baseline(hrv_history, "hrv_rmssd_ms", 90).n == HISTORY_DAYS - 1


def test_baselines_are_recomputed_in_place(hrv_history) -> None:
    """M2-T02/T07: recomputing updates the same (metric, window) rows, never duplicates."""
    recompute_baselines(hrv_history, REFERENCE)
    first = {(b.metric, b.window): b.id for b in hrv_history.query(Baseline).all()}

    recompute_baselines(hrv_history, REFERENCE)
    hrv_history.expire_all()
    second = {(b.metric, b.window): b.id for b in hrv_history.query(Baseline).all()}

    assert first == second


def test_z_score_needs_enough_history_and_real_spread() -> None:
    """M2-T07: no z-score below 14 samples or without spread — that number would be noise."""
    assert z_score(60.0, mean=55.0, sd=5.0, n=30) == 1.0
    assert z_score(47.5, mean=55.0, sd=5.0, n=30) == -1.5
    assert z_score(60.0, mean=55.0, sd=5.0, n=13) is None
    assert z_score(60.0, mean=55.0, sd=0.0, n=30) is None
    assert z_score(None, mean=55.0, sd=5.0, n=30) is None
