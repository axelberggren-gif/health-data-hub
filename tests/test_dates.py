"""Day attribution (see docs/specs/TEST_SPEC_V1.md, M1 — decision D1 of the V1 tech spec).

Every derived `date` key is a **local** date in `Settings.home_timezone`, and each canonical
row type has its own attribution rule: sleep by wake date, recovery by its sleep's wake date,
workouts/cycles by start, air readings by the night window they fall inside. These tests pin
those rules — including the timezone conversions and DST edges that a naive UTC-bucketing
implementation gets wrong.
"""

from __future__ import annotations

from datetime import date

from app.derived.dates import (
    attribute_recovery,
    event_local_date,
    night_air_readings,
    night_sleep_for_date,
    night_window,
    sleep_wake_date,
)
from tests.factories import local, make_air_reading, make_recovery, make_sleep, make_workout, utc


def test_sleep_attributes_to_its_wake_date() -> None:
    """M1-T01: a sleep ending 2026-06-10 07:12 local wakes on 2026-06-10."""
    assert sleep_wake_date(local(2026, 6, 10, 7, 12)) == date(2026, 6, 10)


def test_sleep_crossing_midnight_attributes_to_the_wake_date() -> None:
    """M1-T02: 2026-06-09 22:30 → 2026-06-10 06:40 belongs to 2026-06-10, not the 9th."""
    assert sleep_wake_date(local(2026, 6, 10, 6, 40)) == date(2026, 6, 10)


def test_nap_is_excluded_from_the_nightly_sleep(clean_db) -> None:
    """M1-T03: the nightly selector ignores naps; a nap-only day has no night sleep."""
    day = date(2026, 6, 11)
    nap = make_sleep(
        clean_db, start=local(2026, 6, 11, 14, 0), end=local(2026, 6, 11, 15, 0), nap=True
    )
    assert night_sleep_for_date(clean_db, day) is None

    night = make_sleep(
        clean_db, start=local(2026, 6, 10, 23, 0), end=local(2026, 6, 11, 7, 0), nap=False
    )
    selected = night_sleep_for_date(clean_db, day)
    assert selected is not None
    assert selected.id == night.id
    assert selected.id != nap.id


def test_wake_date_converts_from_utc_instead_of_bucketing_it() -> None:
    """M1-T04: 2026-06-09 23:30 UTC is 01:30 CEST on the 10th → wake date 2026-06-10."""
    assert sleep_wake_date(utc(2026, 6, 9, 23, 30)) == date(2026, 6, 10)


def test_dst_transitions_do_not_misbucket() -> None:
    """M1-T05: the spring-forward and fall-back nights resolve without exceptions."""
    # 2026-03-29: 02:00 CET → 03:00 CEST at 01:00 UTC, so 01:30 UTC is 03:30 local.
    assert sleep_wake_date(utc(2026, 3, 29, 1, 30)) == date(2026, 3, 29)
    # 2026-10-25: 03:00 CEST → 02:00 CET at 01:00 UTC, so 01:30 UTC is 02:30 local.
    assert sleep_wake_date(utc(2026, 10, 25, 1, 30)) == date(2026, 10, 25)


def test_recovery_follows_its_sleep_then_falls_back_to_recorded_at(clean_db) -> None:
    """M1-T06: `sleep_id` wins when it resolves; otherwise the recorded_at local date."""
    sleep = make_sleep(clean_db, end=local(2026, 6, 13, 7, 0), external_id="m1t06-sleep")
    linked = make_recovery(
        clean_db, sleep_id=sleep.source_external_id, recorded_at=local(2026, 6, 14, 9, 0)
    )
    assert attribute_recovery(clean_db, linked) == date(2026, 6, 13)

    dangling = make_recovery(
        clean_db, sleep_id="does-not-exist", recorded_at=local(2026, 6, 14, 9, 0)
    )
    assert attribute_recovery(clean_db, dangling) == date(2026, 6, 14)

    unlinked = make_recovery(clean_db, sleep_id=None, recorded_at=local(2026, 6, 15, 9, 0))
    assert attribute_recovery(clean_db, unlinked) == date(2026, 6, 15)


def test_workouts_and_cycles_attribute_to_their_start_date(clean_db) -> None:
    """M1-T07: a workout starting 23:50 belongs to that day, even though it ends the next."""
    workout = make_workout(
        clean_db, start=local(2026, 6, 10, 23, 50), end=local(2026, 6, 11, 0, 30)
    )
    assert event_local_date(workout.start) == date(2026, 6, 10)
    # Same rule for cycles — both go through `event_local_date` on `start`.
    assert event_local_date(local(2026, 6, 10, 23, 50)) == date(2026, 6, 10)


def test_night_window_selects_only_readings_inside_the_sleep(clean_db) -> None:
    """M1-T08: the window is the night's sleep span; readings outside it are excluded."""
    day = date(2026, 6, 12)
    assert night_window(clean_db, day) is None

    make_sleep(clean_db, start=local(2026, 6, 11, 23, 0), end=local(2026, 6, 12, 7, 0))
    window = night_window(clean_db, day)
    assert window is not None

    before = make_air_reading(clean_db, recorded_at=local(2026, 6, 11, 22, 30))
    inside_early = make_air_reading(clean_db, recorded_at=local(2026, 6, 11, 23, 30))
    inside_late = make_air_reading(clean_db, recorded_at=local(2026, 6, 12, 3, 0))
    after = make_air_reading(clean_db, recorded_at=local(2026, 6, 12, 7, 30))

    selected = {r.id for r in night_air_readings(clean_db, day)}
    assert selected == {inside_early.id, inside_late.id}
    assert before.id not in selected
    assert after.id not in selected
