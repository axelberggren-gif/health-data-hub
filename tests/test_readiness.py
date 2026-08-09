"""Readiness score v1 (see docs/specs/TEST_SPEC_V1.md, M2 — tech spec §6).

Readiness is a transparent weighted blend, not a model, and the point of these tests is
that it stays transparent: the arithmetic is exact, missing components renormalise the
weights instead of being silently treated as zero, and a missing recovery score produces
`None` rather than an invented number.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.derived.jobs import run_daily_derivation
from app.derived.readiness import air_score
from app.models import DailySummary
from tests.factories import local, make_air_reading, make_recovery, make_sleep


def _summary(db, day: date) -> DailySummary:
    row = db.query(DailySummary).filter(DailySummary.date == day).one()
    return row


def _components(row: DailySummary) -> dict[str, float]:
    return {c["component"]: c["value"] for c in (row.readiness_components or [])}


def test_readiness_blends_all_three_components(clean_db) -> None:
    """M2-T03: 0.5·60 + 0.3·80 + 0.2·100 = 74.0, with every component recorded."""
    day = date(2026, 6, 20)
    sleep = make_sleep(
        clean_db, start=local(2026, 6, 19, 23, 0), end=local(2026, 6, 20, 6, 0), performance=80.0
    )
    make_recovery(clean_db, score=60.0, sleep_id=sleep.source_external_id)
    # Clean air: eCO2 800 (<=1000), 19 C (inside 16-21), 45 % (inside 30-60) -> env 100.
    make_air_reading(clean_db, recorded_at=local(2026, 6, 20, 1, 0), eco2=800.0, temp=19.0)

    run_daily_derivation(clean_db, days_back=1, today=day)

    row = _summary(clean_db, day)
    assert row.readiness_score == 74.0
    assert _components(row) == {"recovery": 60.0, "sleep": 80.0, "environment": 100.0}
    assert {c["component"]: c["weight"] for c in row.readiness_components} == {
        "recovery": 0.5,
        "sleep": 0.3,
        "environment": 0.2,
    }


def test_readiness_renormalises_when_air_data_is_missing(clean_db) -> None:
    """M2-T04: (0.5·60 + 0.3·80) / 0.8 = 67.5 — no air data, no environment component."""
    day = date(2026, 5, 1)  # pre-dates the Mill sensor, so this mirrors real history
    sleep = make_sleep(
        clean_db, start=local(2026, 4, 30, 23, 0), end=local(2026, 5, 1, 6, 0), performance=80.0
    )
    make_recovery(clean_db, score=60.0, sleep_id=sleep.source_external_id)

    run_daily_derivation(clean_db, days_back=1, today=day)

    row = _summary(clean_db, day)
    assert row.readiness_score == 67.5
    assert "environment" not in _components(row)
    assert row.night_eco2_ppm_avg is None


def test_no_recovery_means_no_readiness(clean_db) -> None:
    """M2-T05: readiness is never invented — a missing recovery score yields None."""
    day = date(2026, 6, 21)
    make_sleep(
        clean_db, start=local(2026, 6, 20, 23, 0), end=local(2026, 6, 21, 6, 0), performance=80.0
    )

    run_daily_derivation(clean_db, days_back=1, today=day)

    row = _summary(clean_db, day)
    assert row.sleep_performance_pct == 80.0  # the day was rolled up...
    assert row.readiness_score is None  # ...it just has no readiness
    assert row.readiness_components is None


def test_calibrating_recovery_counts_as_missing(clean_db) -> None:
    """M2-T05: a WHOOP score from a calibrating device is not a usable recovery score."""
    day = date(2026, 6, 22)
    sleep = make_sleep(
        clean_db, start=local(2026, 6, 21, 23, 0), end=local(2026, 6, 22, 6, 0), performance=80.0
    )
    make_recovery(clean_db, score=60.0, sleep_id=sleep.source_external_id, user_calibrating=True)

    run_daily_derivation(clean_db, days_back=1, today=day)

    row = _summary(clean_db, day)
    assert row.recovery_score == 60.0  # stored for the record...
    assert row.readiness_score is None  # ...but not blended into readiness


@pytest.mark.parametrize(
    ("eco2", "temp", "humidity", "expected"),
    [
        (800.0, 19.0, 45.0, 100.0),  # everything in band
        (1100.0, 19.0, 45.0, 75.0),  # eCO2 over 1000 -> -25
        (1500.0, 19.0, 45.0, 60.0),  # eCO2 over 1400 -> -40 (not -25-40)
        (800.0, 23.0, 45.0, 85.0),  # too warm -> -15
        (800.0, 19.0, 25.0, 90.0),  # too dry -> -10
        (1500.0, 23.0, 25.0, 35.0),  # 60 - 15 - 10
        (800.0, 14.0, 70.0, 75.0),  # cold and humid: the bands are two-sided
    ],
)
def test_air_score_penalties(eco2: float, temp: float, humidity: float, expected: float) -> None:
    """M2-T06: each environmental penalty is exact and they stack."""
    assert air_score(eco2, temp, humidity) == expected


def test_air_score_never_goes_negative() -> None:
    """M2-T06: the score clamps at 0 so future penalty tuning can't produce nonsense."""
    assert air_score(50_000.0, -20.0, 0.0) >= 0.0


def test_air_score_is_none_without_any_air_data() -> None:
    """M2-T06: no readings means no environment component (M2-T04's precondition)."""
    assert air_score(None, None, None) is None
