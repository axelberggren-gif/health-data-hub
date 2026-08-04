"""Day attribution (see docs/specs/TEST_SPEC_V1.md, M1).

Every derived table is keyed by a **local** date, so these rules decide which day a night's
sleep, a recovery score, a workout and a set of air readings belong to. Get them wrong and
every rollup, baseline and correlation downstream is quietly wrong — hence the boundary and
DST cases here.

Tests that query by date use dates no other test uses: the suite shares one temp database
and the factories commit (see `tests/factories.py`).
"""

from __future__ import annotations

from datetime import date

from app.derived.dates import (
    attribute_recovery,
    event_local_date,
    night_sleep_for_date,
    night_window,
    sleep_wake_date,
)
from tests.factories import local, make_air_reading, make_cycle, make_recovery, make_sleep
from tests.factories import make_workout, utc


def test_sleep_attributes_to_the_wake_date() -> None:
    """M1-T01: a sleep ending 2026-06-10 07:12 local belongs to 2026-06-10."""
    assert sleep_wake_date(local(2026, 6, 10, 7, 12)) == date(2026, 6, 10)


def test_sleep_crossing_midnight_attributes_to_the_morning() -> None:
    """M1-T02: 2026-06-09 22:30 -> 2026-06-10 06:40 belongs to the wake date, not bedtime."""
    assert sleep_wake_date(local(2026, 6, 10, 6, 40)) == date(2026, 6, 10)


def test_wake_date_converts_the_timezone_rather_than_bucketing_utc() -> None:
    """M1-T04: 2026-06-09 23:30 UTC is 01:30 local (CEST) -> 2026-06-10, not 2026-06-09."""
    assert sleep_wake_date(utc(2026, 6, 9, 23, 30)) == date(2026, 6, 10)


def test_naive_timestamps_are_read_as_utc() -> None:
    """M1-T04: SQLite hands datetimes back without a timezone; they are UTC, not local."""
    from datetime import datetime

    assert sleep_wake_date(datetime(2026, 6, 9, 23, 30)) == date(2026, 6, 10)


def test_spring_forward_night_does_not_misbucket() -> None:
    """M1-T05: CET->CEST night — 2026-03-29 01:30 UTC is 03:30 CEST on the 29th."""
    assert sleep_wake_date(utc(2026, 3, 29, 1, 30)) == date(2026, 3, 29)


def test_fall_back_night_does_not_misbucket() -> None:
    """M1-T05: CEST->CET night — 2026-10-25 05:00 UTC is 06:00 CET on the 25th."""
    assert sleep_wake_date(utc(2026, 10, 25, 5, 0)) == date(2026, 10, 25)


def test_fall_back_repeated_hour_resolves_to_the_same_date() -> None:
    """M1-T05: both passes of the repeated 02:00-03:00 local hour stay on 2026-10-25."""
    assert sleep_wake_date(utc(2026, 10, 25, 0, 30)) == date(2026, 10, 25)  # 02:30 CEST
    assert sleep_wake_date(utc(2026, 10, 25, 1, 30)) == date(2026, 10, 25)  # 02:30 CET


def test_workouts_and_cycles_attribute_to_their_start_date(db) -> None:
    """M1-T07: a workout starting 23:50 local belongs to that day, not the day it ends."""
    workout = make_workout(db, start=local(2026, 6, 10, 23, 50), end=local(2026, 6, 11, 0, 40))
    cycle = make_cycle(db, start=local(2026, 6, 10, 23, 50))

    assert event_local_date(workout.start) == date(2026, 6, 10)
    assert event_local_date(cycle.start) == date(2026, 6, 10)


def test_nightly_selector_ignores_naps(db) -> None:
    """M1-T03: with a night sleep and a nap on the same date, the night session wins."""
    day = date(2026, 5, 4)
    night = make_sleep(db, start=local(2026, 5, 3, 23, 0), end=local(2026, 5, 4, 7, 0))
    make_sleep(db, start=local(2026, 5, 4, 14, 0), end=local(2026, 5, 4, 15, 0), nap=True)

    selected = night_sleep_for_date(db, day)

    assert selected is not None
    assert selected.id == night.id


def test_nightly_selector_returns_none_for_a_nap_only_day(db) -> None:
    """M1-T03: a day with only a nap has no night sleep."""
    make_sleep(db, start=local(2026, 5, 6, 14, 0), end=local(2026, 5, 6, 15, 0), nap=True)

    assert night_sleep_for_date(db, date(2026, 5, 6)) is None


def test_recovery_follows_its_linked_sleep(db) -> None:
    """M1-T06: recovery with a resolvable sleep_id takes that sleep's wake date."""
    make_sleep(
        db,
        start=local(2026, 5, 8, 23, 0),
        end=local(2026, 5, 9, 7, 0),
        external_id="sleep-m1t06",
    )
    recovery = make_recovery(db, sleep_id="sleep-m1t06", recorded_at=local(2026, 5, 10, 12, 0))

    # The linked sleep wins over recorded_at, which is a day later here on purpose.
    assert attribute_recovery(recovery, db) == date(2026, 5, 9)


def test_recovery_with_a_dangling_sleep_id_falls_back_to_recorded_at(db) -> None:
    """M1-T06: an unresolvable sleep_id falls back to the local date of recorded_at."""
    recovery = make_recovery(
        db, sleep_id="sleep-does-not-exist", recorded_at=local(2026, 5, 11, 8, 30)
    )

    assert attribute_recovery(recovery, db) == date(2026, 5, 11)


def test_recovery_without_a_sleep_id_uses_recorded_at(db) -> None:
    """M1-T06: no sleep_id at all — same fallback."""
    recovery = make_recovery(db, sleep_id=None, recorded_at=local(2026, 5, 12, 8, 30))

    assert attribute_recovery(recovery, db) == date(2026, 5, 12)


def test_night_window_selects_only_readings_between_sleep_start_and_end(db) -> None:
    """M1-T08: a 23:00->07:00 night selects the 23:30 and 03:00 readings, not 22:30 or 07:30."""
    day = date(2026, 5, 14)
    make_sleep(db, start=local(2026, 5, 13, 23, 0), end=local(2026, 5, 14, 7, 0))
    before = make_air_reading(db, recorded_at=local(2026, 5, 13, 22, 30))
    early = make_air_reading(db, recorded_at=local(2026, 5, 13, 23, 30))
    middle = make_air_reading(db, recorded_at=local(2026, 5, 14, 3, 0))
    after = make_air_reading(db, recorded_at=local(2026, 5, 14, 7, 30))

    window = night_window(db, day)

    assert window is not None
    start, end = window
    selected = {
        reading.id
        for reading in (before, early, middle, after)
        if start <= _aware(reading.recorded_at) <= end
    }
    assert selected == {early.id, middle.id}


def test_night_window_is_none_without_a_sleep(db) -> None:
    """M1-T08: no sleep for the date means no night window (not an empty range)."""
    assert night_window(db, date(2026, 5, 16)) is None


def _aware(moment):
    """Mirror the module's storage contract: a naive stored timestamp is UTC."""
    from datetime import UTC

    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)
