"""Day attribution — M1 of docs/specs/TEST_SPEC_V1.md (tech spec §3 D1).

Every derived `date` key is a **local** date in ``Settings.home_timezone``. These tests
pin the four attribution rules: sleep → wake date, recovery → its sleep's wake date (else
``recorded_at``), cycle/workout → the local date of ``start``, and the night window that
feeds the air-quality aggregate.

Cross-test isolation: ``night_sleep_for_date`` / ``night_window`` query *the whole*
``sleep_session`` table for a given local date, and the suite shares one temp SQLite file.
So the DB-backed tests each own a **distinct date range** (T03 → June 2026, T06 → July
2026, T08 → September 2026) and the tests that only need a value (T01/T02/T04/T05) call the
pure functions without writing any row. Air readings are additionally filtered by a
per-test ``source_external_id`` prefix, so no query here ever means "all rows in the table".
"""

from __future__ import annotations

from datetime import date, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import config
from app.derived import dates
from app.derived.dates import (
    attribute_recovery,
    event_local_date,
    home_timezone,
    night_sleep_for_date,
    night_window,
    sleep_wake_date,
)
from app.models import AirQualityReading

from .factories import (
    as_utc,
    local,
    make_air_reading,
    make_cycle,
    make_recovery,
    make_sleep,
    make_workout,
    utc,
)

# Every case spells the zone out literally rather than reading `Settings.home_timezone`:
# the owner's real `.env` could set another zone, and a test must never depend on it
# (tests/CLAUDE.md). That the *default* is this zone is M0-T02's job; that a tz-less call
# follows `Settings` is covered by `test_tz_defaults_to_the_configured_home_zone` below.
TZ = "Europe/Stockholm"
STOCKHOLM = TZ


def test_sleep_wake_date_uses_the_wake_day() -> None:
    """M1-T01: sleep ending 2026-06-10 07:12 local attributes to the wake date."""
    assert sleep_wake_date(local(2026, 6, 10, 7, 12), TZ) == date(2026, 6, 10)


def test_sleep_crossing_midnight_attributes_to_wake_date() -> None:
    """M1-T02: a sleep 2026-06-09 22:30 -> 2026-06-10 06:40 local belongs to 2026-06-10."""
    start = local(2026, 6, 9, 22, 30)
    end = local(2026, 6, 10, 6, 40)

    assert start.date() == date(2026, 6, 9)  # the night starts on the previous day
    assert sleep_wake_date(end, TZ) == date(2026, 6, 10)


def test_nightly_selector_ignores_naps(db: Session) -> None:
    """M1-T03: the nightly-sleep selector returns the night session, never a nap."""
    night = make_sleep(
        db,
        start=local(2026, 6, 9, 23, 0),
        end=local(2026, 6, 10, 7, 0),
        source_external_id="m1t03-night",
    )
    make_sleep(
        db,
        start=local(2026, 6, 10, 14, 0),
        end=local(2026, 6, 10, 15, 0),
        nap=True,
        source_external_id="m1t03-nap-same-day",
    )

    selected = night_sleep_for_date(db, date(2026, 6, 10))

    assert selected is not None
    assert selected.id == night.id
    assert selected.source_external_id == "m1t03-night"
    assert not selected.nap


def test_nightly_selector_returns_none_for_a_nap_only_day(db: Session) -> None:
    """M1-T03: with *only* a nap on that date the selector returns None."""
    make_sleep(
        db,
        start=local(2026, 6, 14, 14, 0),
        end=local(2026, 6, 14, 15, 0),
        nap=True,
        source_external_id="m1t03-nap-only",
    )

    assert night_sleep_for_date(db, date(2026, 6, 14)) is None


@pytest.mark.parametrize(
    "end_value",
    [
        pytest.param(utc(2026, 6, 9, 23, 30), id="aware-utc"),
        # Stored rows come back from SQLite without tzinfo, so a naive value must be
        # read as UTC too — never as a local wall clock.
        pytest.param(datetime(2026, 6, 9, 23, 30), id="naive-is-utc"),
    ],
)
def test_wake_date_converts_timezone_instead_of_bucketing_utc(end_value: datetime) -> None:
    """M1-T04: timezone conversion, not UTC bucketing (23:30 UTC = 01:30 local CEST)."""
    assert sleep_wake_date(end_value, STOCKHOLM) == date(2026, 6, 10)


@pytest.mark.parametrize(
    ("end_utc", "expected"),
    [
        # Spring forward: CET->CEST at 01:00 UTC on 2026-03-29 (02:00 -> 03:00 local).
        pytest.param(utc(2026, 3, 29, 0, 30), date(2026, 3, 29), id="before-spring-forward"),
        pytest.param(utc(2026, 3, 29, 1, 30), date(2026, 3, 29), id="after-spring-forward"),
        # Fall back: CEST->CET at 01:00 UTC on 2026-10-25; local 02:30 happens twice.
        pytest.param(utc(2026, 10, 24, 21, 0), date(2026, 10, 24), id="evening-before-fall-back"),
        pytest.param(utc(2026, 10, 25, 0, 30), date(2026, 10, 25), id="ambiguous-hour-first-pass"),
        pytest.param(utc(2026, 10, 25, 1, 30), date(2026, 10, 25), id="ambiguous-hour-second-pass"),
        pytest.param(utc(2026, 10, 25, 5, 0), date(2026, 10, 25), id="after-fall-back"),
    ],
)
def test_dst_transitions_do_not_crash_or_misbucket(end_utc: datetime, expected: date) -> None:
    """M1-T05: DST transitions don't crash or misbucket the wake date."""
    assert sleep_wake_date(end_utc, STOCKHOLM) == expected


def test_recovery_attributes_to_its_linked_sleep(db: Session) -> None:
    """M1-T06: recovery whose sleep_id resolves takes that sleep's wake date."""
    make_sleep(
        db,
        start=local(2026, 7, 14, 23, 15),
        end=local(2026, 7, 15, 6, 45),
        source_external_id="m1t06-sleep",
    )
    # recorded_at deliberately falls on a *different* local date, so a passing assert
    # can only mean the sleep link was followed.
    recovery = make_recovery(
        db,
        sleep_id="m1t06-sleep",
        recorded_at=local(2026, 7, 16, 9, 0),
        source_external_id="m1t06-recovery-linked",
    )

    assert attribute_recovery(recovery, db) == date(2026, 7, 15)


@pytest.mark.parametrize(
    ("sleep_id", "external_id"),
    [
        pytest.param("m1t06-no-such-sleep", "m1t06-recovery-dangling", id="dangling-sleep-id"),
        pytest.param(None, "m1t06-recovery-unlinked", id="absent-sleep-id"),
    ],
)
def test_recovery_falls_back_to_recorded_at(
    db: Session, sleep_id: str | None, external_id: str
) -> None:
    """M1-T06: a dangling or absent sleep_id falls back to the local date of recorded_at."""
    # 23:30 local on 2026-07-19 is 21:30 UTC the same day, so the fallback must also
    # convert rather than take the raw UTC date.
    recovery = make_recovery(
        db,
        sleep_id=sleep_id,
        recorded_at=local(2026, 7, 19, 23, 30),
        source_external_id=external_id,
    )

    assert attribute_recovery(recovery, db) == date(2026, 7, 19)


def test_workout_and_cycle_attribute_to_their_start_date(db: Session) -> None:
    """M1-T07: a workout/cycle starting 2026-06-10 23:50 local belongs to 2026-06-10."""
    workout = make_workout(
        db,
        start=local(2026, 6, 10, 23, 50),
        end=local(2026, 6, 11, 0, 50),
        source_external_id="m1t07-workout",
    )
    # This cycle relies on the factory's auto-generated id (the shared counter).
    cycle = make_cycle(db, start=local(2026, 6, 10, 23, 50), end=local(2026, 6, 11, 12, 0))

    assert event_local_date(workout.start, TZ) == date(2026, 6, 10)
    assert event_local_date(cycle.start, TZ) == date(2026, 6, 10)


def test_night_window_selects_only_readings_inside_the_night(db: Session) -> None:
    """M1-T08: the night window spans the night's sleep and selects only its readings."""
    make_sleep(
        db,
        start=local(2026, 9, 9, 23, 0),
        end=local(2026, 9, 10, 7, 0),
        source_external_id="m1t08-night",
    )
    outside_before = make_air_reading(
        db, recorded_at=local(2026, 9, 9, 22, 30), eco2=700.0, source_external_id="m1t08-air-2230"
    )
    inside_early = make_air_reading(
        db, recorded_at=local(2026, 9, 9, 23, 30), eco2=900.0, source_external_id="m1t08-air-2330"
    )
    inside_late = make_air_reading(
        db, recorded_at=local(2026, 9, 10, 3, 0), eco2=1000.0, source_external_id="m1t08-air-0300"
    )
    outside_after = make_air_reading(
        db, recorded_at=local(2026, 9, 10, 7, 30), eco2=1100.0, source_external_id="m1t08-air-0730"
    )

    window = night_window(db, date(2026, 9, 10))

    assert window is not None
    start, end = window
    # Bounds are normalised to aware UTC before querying: SQLite stores these columns
    # naive-UTC, so comparing against a local-zone datetime would silently compare
    # wall clocks. Rows are scoped to this test's id prefix.
    readings = db.scalars(
        select(AirQualityReading)
        .where(
            AirQualityReading.source_external_id.like("m1t08-air-%"),
            AirQualityReading.recorded_at >= as_utc(start),
            AirQualityReading.recorded_at <= as_utc(end),
        )
        .order_by(AirQualityReading.recorded_at)
    ).all()

    assert len(readings) == 2
    assert [r.id for r in readings] == [inside_early.id, inside_late.id]
    assert {r.eco2_ppm for r in readings} == {900.0, 1000.0}
    assert outside_before.id not in {r.id for r in readings}
    assert outside_after.id not in {r.id for r in readings}


def test_night_window_is_none_without_a_sleep(db: Session) -> None:
    """M1-T08: with no sleep session for the date the night window is None."""
    assert night_window(db, date(2026, 9, 20)) is None


def test_tz_defaults_to_the_configured_home_zone(monkeypatch: pytest.MonkeyPatch) -> None:
    """M1-T04: omitting `tz` uses Settings.home_timezone, not the server's local zone.

    Pinned with a fabricated zone far from the default so a passing assert can only mean
    the setting was consulted (the other cases pass the zone explicitly to stay hermetic).
    """
    monkeypatch.setenv("HOME_TIMEZONE", "Pacific/Kiritimati")  # UTC+14
    # `_env_file=None` keeps this hermetic: env only, never the owner's real `.env`.
    # Patched on the `dates` module because that is where the name is bound.
    monkeypatch.setattr(dates, "get_settings", lambda: config.Settings(_env_file=None))

    assert home_timezone() == "Pacific/Kiritimati"
    # 23:30 UTC on the 9th is already 13:30 on the 10th at UTC+14.
    assert sleep_wake_date(utc(2026, 6, 9, 23, 30)) == date(2026, 6, 10)
