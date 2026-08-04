"""Anomaly flags and the illness early-warning (see TEST_SPEC_V1.md, M2 — tech spec §8).

These rules are the first thing in the app that tells the owner "something is off", so the
thresholds are tested at the boundary in both directions: the value that should fire, and
the neighbouring value that must not. A flag that fires a day early is noise; one that fires
a day late is useless.

The illness warning is deliberately a **conjunction** — one signal is a bad night, two at
once is a pattern — and its wording stays non-diagnostic.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.derived.baselines import recompute_baselines
from app.derived.flags import apply_flags
from app.models import DailySummary, InsightCard
from tests.factories import make_summary

REFERENCE = date(2026, 6, 30)
WINDOW_DAYS = 30
EIGHT_HOURS_MS = 28_800_000


def _derive(db, reference: date = REFERENCE) -> list[dict]:
    """Run the two derivation steps the flags depend on, in the job's order."""
    recompute_baselines(db, reference)
    apply_flags(db, reference)
    db.expire_all()
    row = db.query(DailySummary).filter(DailySummary.date == reference).one()
    return list(row.flags or [])


def _kinds(flags: list[dict]) -> set[str]:
    return {flag["kind"] for flag in flags}


def _history(db, *, column: str, low: float, high: float, days: int = WINDOW_DAYS) -> None:
    """`days` complete days alternating between `low` and `high`.

    Half at each value means the mean is their midpoint and the population SD is exactly
    half their difference — an exact baseline with no floating-point slack.
    """
    for offset in range(days, 0, -1):
        value = low if offset % 2 == 0 else high
        make_summary(db, day=REFERENCE - timedelta(days=offset), **{column: value})


@pytest.mark.parametrize(
    ("hrv_today", "expected_z", "should_fire"),
    [(47.5, -1.5, True), (48.0, -1.4, False)],
)
def test_hrv_drop_threshold_is_exact(
    clean_db, hrv_today: float, expected_z: float, should_fire: bool
) -> None:
    """M2-T08: HRV z ≤ -1.5 fires. Baseline mean 55, SD 5, so 47.5 is exactly -1.5."""
    _history(clean_db, column="hrv_rmssd_ms", low=50.0, high=60.0)
    make_summary(clean_db, day=REFERENCE, hrv_rmssd_ms=hrv_today)

    flags = _derive(clean_db)

    assert ("hrv_drop" in _kinds(flags)) is should_fire
    if should_fire:
        fired = next(f for f in flags if f["kind"] == "hrv_drop")
        assert fired["z"] == expected_z
        assert fired["metric"] == "hrv_rmssd_ms"


@pytest.mark.parametrize(("rhr_today", "should_fire"), [(57.5, True), (57.0, False)])
def test_rhr_elevated_threshold_is_exact(clean_db, rhr_today: float, should_fire: bool) -> None:
    """M2-T08: RHR z ≥ +1.5 fires. Baseline mean 50, SD 5, so 57.5 is exactly +1.5."""
    _history(clean_db, column="resting_hr_bpm", low=45.0, high=55.0)
    make_summary(clean_db, day=REFERENCE, resting_hr_bpm=rhr_today)

    assert ("rhr_elevated" in _kinds(_derive(clean_db))) is should_fire


def _duration_for_ratio(ratio: float, older: int, n_recent: int = 7, n_total: int = 90) -> int:
    """Recent-window duration whose 7-day mean is `ratio` × the 90-day mean.

    The 7 recent days are *inside* the 90-day window, so solving
    `ratio = A / ((n_recent·A + n_old·older) / n_total)` for A is what makes the ratio exact.
    """
    n_old = n_total - n_recent
    return round(ratio * n_old * older / (n_total - ratio * n_recent))


@pytest.mark.parametrize(("ratio", "should_fire"), [(0.89, True), (0.91, False)])
def test_sleep_debt_threshold_is_exact(clean_db, ratio: float, should_fire: bool) -> None:
    """M2-T08: the 7-day sleep mean firing below 90 % of the 90-day mean, and not above."""
    recent = _duration_for_ratio(ratio, EIGHT_HOURS_MS)
    for offset in range(90, 0, -1):
        duration = recent if offset <= 7 else EIGHT_HOURS_MS
        make_summary(clean_db, day=REFERENCE - timedelta(days=offset), sleep_duration_ms=duration)
    make_summary(clean_db, day=REFERENCE, sleep_duration_ms=recent)

    flags = _derive(clean_db)

    assert ("sleep_debt" in _kinds(flags)) is should_fire
    if should_fire:
        fired = next(f for f in flags if f["kind"] == "sleep_debt")
        assert fired["ratio"] == pytest.approx(ratio, abs=1e-4)


def test_bad_air_streak_needs_three_nights(clean_db) -> None:
    """§8: three consecutive nights over 1000 ppm is a streak; two is not."""
    for offset, eco2 in ((2, 1200.0), (1, 1200.0)):
        make_summary(clean_db, day=REFERENCE - timedelta(days=offset), night_eco2_ppm_avg=eco2)
    make_summary(clean_db, day=REFERENCE, night_eco2_ppm_avg=900.0)
    assert "bad_air_streak" not in _kinds(_derive(clean_db))

    row = clean_db.query(DailySummary).filter(DailySummary.date == REFERENCE).one()
    row.night_eco2_ppm_avg = 1100.0
    clean_db.commit()
    assert "bad_air_streak" in _kinds(_derive(clean_db))


def test_one_signal_does_not_warn_about_illness(clean_db) -> None:
    """M2-T09: a single firing signal is a bad night, not a warning."""
    _history(clean_db, column="hrv_rmssd_ms", low=50.0, high=60.0)
    make_summary(clean_db, day=REFERENCE, hrv_rmssd_ms=47.5)

    flags = _derive(clean_db)

    assert _kinds(flags) == {"hrv_drop"}
    assert clean_db.query(InsightCard).filter(InsightCard.kind == "illness_warning").count() == 0


def test_two_signals_raise_a_non_diagnostic_illness_warning(clean_db) -> None:
    """M2-T09: two of the four signals on one day upsert the illness card."""
    for offset in range(WINDOW_DAYS, 0, -1):
        alternating = offset % 2 == 0
        make_summary(
            clean_db,
            day=REFERENCE - timedelta(days=offset),
            hrv_rmssd_ms=50.0 if alternating else 60.0,
            resting_hr_bpm=45.0 if alternating else 55.0,
        )
    make_summary(clean_db, day=REFERENCE, hrv_rmssd_ms=47.5, resting_hr_bpm=57.5)

    flags = _derive(clean_db)

    assert {"hrv_drop", "rhr_elevated", "illness_warning"} <= _kinds(flags)
    warning = next(f for f in flags if f["kind"] == "illness_warning")
    assert sorted(warning["contributors"]) == ["hrv_drop", "rhr_elevated"]

    card = clean_db.query(InsightCard).filter(InsightCard.kind == "illness_warning").one()
    assert card.status == "active"
    # Non-diagnostic wording is a hard requirement, not a style preference.
    assert not any(word in card.body.lower() for word in ("illness", "sick", "infection", "virus"))


def test_flags_and_cards_are_idempotent(clean_db) -> None:
    """M2-T02/T09: re-evaluating the same day updates cards instead of duplicating them."""
    _history(clean_db, column="hrv_rmssd_ms", low=50.0, high=60.0)
    make_summary(clean_db, day=REFERENCE, hrv_rmssd_ms=47.5)

    first = _derive(clean_db)
    ids = {c.source_external_id: c.id for c in clean_db.query(InsightCard).all()}

    second = _derive(clean_db)

    assert first == second
    clean_db.expire_all()
    assert {c.source_external_id: c.id for c in clean_db.query(InsightCard).all()} == ids


def test_a_flag_that_stops_firing_expires_its_card(clean_db) -> None:
    """§8 lifecycle: a resolved anomaly leaves an expired card, not a stale active one."""
    _history(clean_db, column="hrv_rmssd_ms", low=50.0, high=60.0)
    make_summary(clean_db, day=REFERENCE, hrv_rmssd_ms=47.5)
    _derive(clean_db)
    assert clean_db.query(InsightCard).filter(InsightCard.status == "active").count() == 1

    summary = clean_db.query(DailySummary).filter(DailySummary.date == REFERENCE).one()
    summary.hrv_rmssd_ms = 55.0
    clean_db.commit()

    assert _derive(clean_db) == []
    clean_db.expire_all()
    card = clean_db.query(InsightCard).one()
    assert card.status == "expired"
