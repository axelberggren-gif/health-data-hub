"""The daily derivation job (see docs/specs/TEST_SPEC_V1.md, M2 — tech spec §5).

The job is the derived layer's only write path: canonical rows in, one `daily_summary` row
per local date out, plus baselines and cards. Two properties matter more than any single
number — it is **idempotent** (running it twice changes nothing, the house invariant) and it
**self-heals** (a laptop that slept for three days catches up on its own).
"""

from __future__ import annotations

from datetime import date, timedelta

from app.derived import DERIVED_SOURCE
from app.derived.dates import home_tz
from app.derived.jobs import catch_up_if_stale, newest_summary_date, run_daily_derivation
from app.derived.rollup import (
    AIR_COLUMNS,
    RECOVERY_COLUMNS,
    SLEEP_COLUMNS,
    air_values,
    recovery_values,
    sleep_values,
)
from app.models import Baseline, DailySummary, InsightCard
from tests.factories import (
    local,
    make_air_reading,
    make_cycle,
    make_recovery,
    make_sleep,
    make_summary,
    make_workout,
)

GOLDEN_DAY = date(2026, 6, 10)
SEVEN_HOURS_MS = 25_200_000


def _today() -> date:
    from datetime import datetime

    return datetime.now(home_tz()).date()


def _build_golden_day(db) -> None:
    """The 2026-06-10 fixture set from M2-T01."""
    sleep = make_sleep(
        db,
        start=local(2026, 6, 9, 23, 0),
        end=local(2026, 6, 10, 6, 0),
        performance=80.0,
        debt_ms=1_800_000,
    )
    make_recovery(db, score=60.0, hrv=55.0, rhr=52.0, sleep_id=sleep.source_external_id)
    make_cycle(db, start=local(2026, 6, 10, 6, 0), strain=12.4, kilojoule=9000.0)
    make_workout(db, start=local(2026, 6, 10, 17, 0), strain=8.5)
    for at, eco2 in ((local(2026, 6, 9, 23, 30), 700.0), (local(2026, 6, 10, 1, 0), 900.0)):
        make_air_reading(db, recorded_at=at, eco2=eco2, temp=19.0, humidity=45.0, tvoc=120.0)
    make_air_reading(
        db, recorded_at=local(2026, 6, 10, 4, 0), eco2=800.0, temp=19.0, humidity=45.0, tvoc=120.0
    )


def test_golden_day_rollup(clean_db) -> None:
    """M2-T01: one row for the date, every populated column at its hand-computed value."""
    _build_golden_day(clean_db)

    run_daily_derivation(clean_db, days_back=1, today=GOLDEN_DAY)

    rows = clean_db.query(DailySummary).all()
    assert len(rows) == 1
    row = rows[0]
    assert row.date == GOLDEN_DAY

    # From the recovery attributed to this wake date.
    assert row.recovery_score == 60.0
    assert row.hrv_rmssd_ms == 55.0
    assert row.resting_hr_bpm == 52.0
    assert row.spo2_pct == 97.0
    assert row.skin_temp_c == 33.5

    # From the night's main sleep. 7 h asleep, split 20 % REM / 20 % slow-wave by the factory.
    assert row.sleep_performance_pct == 80.0
    assert row.sleep_efficiency_pct == 90.0
    assert row.sleep_duration_ms == SEVEN_HOURS_MS
    assert row.sleep_debt_ms == 1_800_000
    assert row.rem_ms == SEVEN_HOURS_MS // 5
    assert row.slow_wave_ms == SEVEN_HOURS_MS // 5
    assert row.respiratory_rate == 14.5
    assert row.disturbance_count == 3

    # From the cycle + the day's workouts.
    assert row.day_strain == 12.4
    assert row.workout_count == 1
    assert row.workout_strain_sum == 8.5
    assert row.kilojoule == 9000.0

    # Night-window air: eCO2 700 / 900 / 800 -> avg 800, max 900.
    assert row.night_eco2_ppm_avg == 800.0
    assert row.night_eco2_ppm_max == 900.0
    assert row.night_temp_c_avg == 19.0
    assert row.night_humidity_pct_avg == 45.0
    assert row.night_tvoc_ppb_avg == 120.0

    # 0.5·60 + 0.3·80 + 0.2·100 (clean air) = 74.0
    assert row.readiness_score == 74.0
    assert row.flags == []

    # Sources that only land in M3 leave their columns empty.
    assert row.weather_temp_min_c is None
    assert row.daylight_seconds is None
    assert row.checkin_mood is None
    assert row.alcohol_units is None


def test_derivation_is_idempotent(clean_db) -> None:
    """M2-T02: a second run with unchanged source data is a no-op, not a duplicate."""
    _build_golden_day(clean_db)
    # A second day so the window has more than one row to keep stable.
    sleep = make_sleep(
        clean_db, start=local(2026, 6, 8, 23, 0), end=local(2026, 6, 9, 7, 0), performance=90.0
    )
    make_recovery(clean_db, score=70.0, sleep_id=sleep.source_external_id)

    run_daily_derivation(clean_db, days_back=7, today=GOLDEN_DAY)
    clean_db.expire_all()

    def snapshot() -> tuple[dict, int, int]:
        summaries = {
            row.date: (row.id, row.recovery_score, row.readiness_score, row.sleep_duration_ms)
            for row in clean_db.query(DailySummary).all()
        }
        return summaries, clean_db.query(Baseline).count(), clean_db.query(InsightCard).count()

    before = snapshot()

    run_daily_derivation(clean_db, days_back=7, today=GOLDEN_DAY)
    clean_db.expire_all()
    after = snapshot()

    assert before == after  # same rows, same primary keys, same values
    assert len(before[0]) == 2  # only the two days that actually have data


def test_derived_rows_carry_derived_provenance(clean_db) -> None:
    """M2-T11: derived rows are provenanced and keyed deterministically, via upsert()."""
    _build_golden_day(clean_db)

    run_daily_derivation(clean_db, days_back=1, today=GOLDEN_DAY)
    clean_db.expire_all()

    row = clean_db.query(DailySummary).one()
    assert row.source == DERIVED_SOURCE
    assert row.source_external_id == GOLDEN_DAY.isoformat()

    # Re-running cannot duplicate: the identity key is stable and upsert() finds the row.
    run_daily_derivation(clean_db, days_back=1, today=GOLDEN_DAY)
    clean_db.expire_all()
    assert clean_db.query(DailySummary).count() == 1
    assert clean_db.query(DailySummary).one().id == row.id

    for card in clean_db.query(InsightCard).all():
        assert card.source == DERIVED_SOURCE
        assert card.source_external_id


def test_recomputing_clears_values_whose_source_data_moved(clean_db) -> None:
    """A summary is a pure function of its inputs — a stale column would be a lie.

    Guards the upsert trap: if the rollup omitted absent columns instead of writing `None`,
    re-deriving a day whose sleep was re-attributed elsewhere would keep the old numbers.
    """
    sleep = make_sleep(
        clean_db, start=local(2026, 6, 9, 23, 0), end=local(2026, 6, 10, 6, 0), performance=80.0
    )
    make_cycle(clean_db, start=local(2026, 6, 10, 6, 0), strain=12.4)
    run_daily_derivation(clean_db, days_back=1, today=GOLDEN_DAY)
    clean_db.expire_all()
    assert clean_db.query(DailySummary).one().sleep_performance_pct == 80.0

    # WHOOP re-classifies the session as a nap, so it is no longer that night's sleep.
    sleep.nap = True
    clean_db.commit()

    run_daily_derivation(clean_db, days_back=1, today=GOLDEN_DAY)
    clean_db.expire_all()

    row = clean_db.query(DailySummary).one()
    assert row.sleep_performance_pct is None
    assert row.sleep_duration_ms is None
    assert row.day_strain == 12.4  # the cycle is untouched


def test_rollup_groups_always_return_their_whole_column_set() -> None:
    """The "absent" and "present" branches must agree on the columns they own."""
    empty = {**recovery_values(None), **sleep_values(None), **air_values([])}
    assert set(empty) == set(RECOVERY_COLUMNS) | set(SLEEP_COLUMNS) | set(AIR_COLUMNS)
    assert all(value is None for value in empty.values())


def test_catch_up_fills_the_gap_after_a_stale_period(clean_db) -> None:
    """M2-T10: three stale days self-heal on startup, through yesterday."""
    today = _today()
    make_summary(clean_db, day=today - timedelta(days=3), recovery_score=50.0)

    # WHOOP data arrived for the days the derivation missed.
    for offset in (2, 1):
        day = today - timedelta(days=offset)
        sleep = make_sleep(
            clean_db,
            start=local(day.year, day.month, day.day, 0, 30),
            end=local(day.year, day.month, day.day, 7, 0),
            performance=75.0,
        )
        make_recovery(clean_db, score=65.0, sleep_id=sleep.source_external_id)

    assert newest_summary_date(clean_db) == today - timedelta(days=3)

    report = catch_up_if_stale(clean_db)

    assert report is not None
    clean_db.expire_all()
    derived_days = {row.date for row in clean_db.query(DailySummary).all()}
    assert today - timedelta(days=2) in derived_days
    assert today - timedelta(days=1) in derived_days


def test_catch_up_is_skipped_when_recent(clean_db) -> None:
    """M2-T10: a derivation that ran yesterday is not stale — the 06:00 tick covers today."""
    today = _today()
    make_summary(clean_db, day=today - timedelta(days=1), recovery_score=50.0)

    assert catch_up_if_stale(clean_db) is None


def test_run_endpoint_fills_the_same_gap(clean_db, client) -> None:
    """M2-T10: POST /derived/run reports per-step counts and fills the gap manually."""
    today = _today()
    for offset in (2, 1):
        day = today - timedelta(days=offset)
        sleep = make_sleep(
            clean_db,
            start=local(day.year, day.month, day.day, 0, 30),
            end=local(day.year, day.month, day.day, 7, 0),
            performance=75.0,
        )
        make_recovery(clean_db, score=65.0, sleep_id=sleep.source_external_id)

    response = client.post("/derived/run", params={"days_back": 3})

    assert response.status_code == 200
    body = response.json()
    assert body["counts"]["daily_summary"] == 2
    assert body["days_back"] == 3

    clean_db.expire_all()
    derived_days = {row.date for row in clean_db.query(DailySummary).all()}
    assert derived_days == {today - timedelta(days=2), today - timedelta(days=1)}
