"""Day attribution — M1 of docs/specs/TEST_SPEC_V1.md (tech spec §3 D1).

Every derived `date` key is a **local** date in ``Settings.home_timezone``. These tests
pin the four attribution rules: sleep → wake date, recovery → its sleep's wake date (else
``recorded_at``), cycle/workout → the local date of ``start``, and the night window that
feeds the air-quality aggregate.

Two house rules shape how this module is written.

**Hermetic timezone.** Every call passes ``tz`` explicitly. `get_settings()` reads the
owner's real `.env`, so a test that relied on the *configured* zone would go red on his
laptop the moment he sets `HOME_TIMEZONE` while staying green in CI (which has no `.env`)
— breaking "green locally == green in CI". The one test that does exercise the
`Settings`-backed default patches the setting instead of inheriting it.

**Disjoint dates.** ``night_sleep_for_date`` / ``night_window`` scan the whole
``sleep_session`` table for a local date, and the suite shares one temp SQLite file, so
every DB-writing test owns dates no other test writes:

===========================  ====================================================
2026-03-29 / 03-30           DST spring-forward day length
2026-05-12, 05-14            nap exclusion (M1-T03)
2026-05-18, 05-19            fragmented-night ordering + tie-break
2026-05-20 / 05-21           the exactly-midnight boundary
2026-07-15, 07-20, 07-25/28  recovery attribution (M1-T06)
2026-08-11                   workout + cycle start rule (M1-T07)
2026-09-09/10, 09-15/16      night window (M1-T08)
===========================  ====================================================

**2026-06-10 is deliberately absent from that table**: M2-T01 fixes it as its golden-day
date, and a stray sleep here would outrank M2's own fixture and corrupt its assertions.
The pure-function tests (M1-T01/T02/T04/T05) use June dates freely — they write no rows.
"""

from __future__ import annotations

import time
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import config
from app.derived import dates
from app.derived.dates import (
    attribute_recovery,
    event_local_date,
    home_timezone,
    local_day_bounds_utc,
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

TZ = "Europe/Stockholm"
STOCKHOLM = TZ


# --------------------------------------------------------------------------
# M1-T01 / M1-T02 — the wake-date rule
# --------------------------------------------------------------------------
def test_sleep_wake_date_uses_the_wake_day() -> None:
    """M1-T01: sleep ending 2026-06-10 07:12 local attributes to the wake date."""
    assert sleep_wake_date(local(2026, 6, 10, 7, 12), TZ) == date(2026, 6, 10)


def test_sleep_crossing_midnight_attributes_to_wake_date() -> None:
    """M1-T02: a sleep 2026-06-09 22:30 -> 2026-06-10 06:40 local belongs to 2026-06-10."""
    start = local(2026, 6, 9, 22, 30)
    end = local(2026, 6, 10, 6, 40)

    assert start.date() == date(2026, 6, 9)  # the night starts on the previous day
    assert sleep_wake_date(end, TZ) == date(2026, 6, 10)


# --------------------------------------------------------------------------
# M1-T03 — naps are never the night's sleep
# --------------------------------------------------------------------------
def test_nightly_selector_ignores_naps(db: Session) -> None:
    """M1-T03: the nightly-sleep selector returns the night session, never a nap.

    The nap is deliberately *longer* than the night sleep (a rough 2.5 h night against a
    3 h afternoon nap). With the catalog's 1 h nap against a normal 8 h night, "longest
    session wins" would pick the night session anyway and the test would still pass even
    if naps were not excluded at all — so the exclusion has to be what makes this green.
    """
    night = make_sleep(
        db,
        start=local(2026, 5, 12, 3, 0),
        end=local(2026, 5, 12, 5, 30),
        source_external_id="m1t03-night",
    )
    make_sleep(
        db,
        start=local(2026, 5, 12, 13, 0),
        end=local(2026, 5, 12, 16, 0),
        nap=True,
        source_external_id="m1t03-nap-same-day",
    )

    selected = night_sleep_for_date(db, date(2026, 5, 12), TZ)

    assert selected is not None
    assert selected.id == night.id
    assert selected.source_external_id == "m1t03-night"
    assert not selected.nap


def test_nightly_selector_returns_none_for_a_nap_only_day(db: Session) -> None:
    """M1-T03: with *only* a nap on that date the selector returns None."""
    make_sleep(
        db,
        start=local(2026, 5, 14, 14, 0),
        end=local(2026, 5, 14, 15, 0),
        nap=True,
        source_external_id="m1t03-nap-only",
    )

    assert night_sleep_for_date(db, date(2026, 5, 14), TZ) is None


def test_fragmented_night_returns_the_longest_session(db: Session) -> None:
    """M1-T03: several night sessions on one date -> the longest one wins.

    Pins the ordering rule that TEST_SPEC deviation #3 documents. Without it the
    selector could return either session and `daily_summary` would take its sleep
    duration from whichever row the database happened to hand back first.
    """
    make_sleep(
        db,
        start=local(2026, 5, 18, 2, 0),
        end=local(2026, 5, 18, 3, 0),  # 1h
        source_external_id="m1t03-fragment-short",
    )
    main = make_sleep(
        db,
        start=local(2026, 5, 18, 3, 30),
        end=local(2026, 5, 18, 7, 0),  # 3.5h — the main stretch
        source_external_id="m1t03-fragment-long",
    )

    selected = night_sleep_for_date(db, date(2026, 5, 18), TZ)

    assert selected is not None
    assert selected.id == main.id


def test_equal_length_sessions_break_the_tie_on_the_later_end(db: Session) -> None:
    """M1-T03: equal-duration night sessions tie-break on the later `end`."""
    make_sleep(
        db,
        start=local(2026, 5, 19, 1, 0),
        end=local(2026, 5, 19, 3, 0),  # 2h
        source_external_id="m1t03-tie-earlier",
    )
    later = make_sleep(
        db,
        start=local(2026, 5, 19, 4, 0),
        end=local(2026, 5, 19, 6, 0),  # 2h, ends later
        source_external_id="m1t03-tie-later",
    )

    selected = night_sleep_for_date(db, date(2026, 5, 19), TZ)

    assert selected is not None
    assert selected.id == later.id


# --------------------------------------------------------------------------
# M1-T04 — conversion, not UTC bucketing
# --------------------------------------------------------------------------
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
    ("value", "expected"),
    [
        # A naive value is *read as* UTC. Asserting on the instant (not a date) is what
        # makes this bite: reading it as server-local instead is invisible in CI, where
        # the system zone already is UTC.
        pytest.param(datetime(2026, 6, 9, 23, 30), utc(2026, 6, 9, 23, 30), id="naive-read-as-utc"),
        # An aware value is *converted*, not relabelled: 01:30 CEST is 23:30 UTC the
        # previous day. Relabelling would keep the 01:30 wall clock and shift the instant.
        pytest.param(local(2026, 6, 10, 1, 30), utc(2026, 6, 9, 23, 30), id="aware-is-converted"),
        pytest.param(utc(2026, 6, 9, 23, 30), utc(2026, 6, 9, 23, 30), id="utc-unchanged"),
    ],
)
def test_as_utc_normalises_to_the_same_instant(value: datetime, expected: datetime) -> None:
    """M1-T04: `as_utc` preserves the instant — naive means UTC, aware gets converted."""
    assert dates.as_utc(value) == expected


@pytest.mark.skipif(not hasattr(time, "tzset"), reason="tzset() is POSIX-only")
def test_as_utc_reads_naive_as_utc_not_as_server_local(monkeypatch: pytest.MonkeyPatch) -> None:
    """M1-T04: a naive datetime is UTC even when the *server's* own zone is not.

    The store hands naive UTC values back, so interpreting them as server-local would
    shift every instant by the host's offset — silently, on the owner's laptop only. CI
    runs in UTC, where that bug is invisible: `datetime.astimezone(UTC)` on a naive value
    is a no-op there. Forcing the process zone is what makes this test bite anywhere.
    """
    monkeypatch.setenv("TZ", "Asia/Tokyo")  # UTC+9, no DST to complicate the arithmetic
    time.tzset()
    try:
        stored = datetime(2026, 6, 9, 23, 30)  # as SQLite hands it back: naive UTC

        assert dates.as_utc(stored) == utc(2026, 6, 9, 23, 30)
        # Read as Tokyo local instead, this instant would be 14:30 UTC — still the 9th in
        # Stockholm, so the whole night would be attributed to the wrong day.
        assert sleep_wake_date(stored, STOCKHOLM) == date(2026, 6, 10)
    finally:
        monkeypatch.undo()
        time.tzset()  # restore libc's cached zone for the rest of the session


@pytest.mark.parametrize(
    ("tz", "expected"),
    [
        pytest.param(STOCKHOLM, date(2026, 6, 10), id="stockholm-plus-2"),
        pytest.param("Pacific/Kiritimati", date(2026, 6, 10), id="kiritimati-plus-14"),
        # West of UTC the same instant is still the *previous* day, so a function that
        # ignored `tz` and always used one zone could not satisfy all three rows.
        pytest.param("America/Los_Angeles", date(2026, 6, 9), id="los-angeles-minus-7"),
    ],
)
def test_the_tz_argument_is_honoured(tz: str, expected: date) -> None:
    """M1-T04: the same instant maps to different local dates per zone."""
    assert sleep_wake_date(utc(2026, 6, 9, 23, 30), tz) == expected


def test_tz_defaults_to_the_configured_home_zone(monkeypatch: pytest.MonkeyPatch) -> None:
    """M1-T04: omitting `tz` uses Settings.home_timezone, not the server's local zone.

    Pinned with a zone far from the default so a passing assert can only mean the setting
    was consulted (every other case passes the zone explicitly to stay hermetic).
    """
    monkeypatch.setenv("HOME_TIMEZONE", "Pacific/Kiritimati")  # UTC+14
    # `_env_file=None` keeps this hermetic: env only, never the owner's real `.env`.
    # Patched on the `dates` module because that is where the name is bound.
    monkeypatch.setattr(dates, "get_settings", lambda: config.Settings(_env_file=None))

    assert home_timezone() == "Pacific/Kiritimati"
    # 23:30 UTC on the 9th is already 13:30 on the 10th at UTC+14.
    assert sleep_wake_date(utc(2026, 6, 9, 23, 30)) == date(2026, 6, 10)


# --------------------------------------------------------------------------
# M1-T05 — DST
# --------------------------------------------------------------------------
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


@pytest.mark.parametrize(
    ("day", "start", "end", "hours"),
    [
        pytest.param(
            date(2026, 6, 10), utc(2026, 6, 9, 22, 0), utc(2026, 6, 10, 22, 0), 24, id="normal-day"
        ),
        # Spring forward: 02:00 local never happens, so the local day is only 23 h long.
        pytest.param(
            date(2026, 3, 29), utc(2026, 3, 28, 23, 0), utc(2026, 3, 29, 22, 0), 23, id="23h-day"
        ),
        # Fall back: 02:00 local happens twice, so the local day is 25 h long.
        pytest.param(
            date(2026, 10, 25), utc(2026, 10, 24, 22, 0), utc(2026, 10, 25, 23, 0), 25, id="25h-day"
        ),
    ],
)
def test_local_day_bounds_track_dst_day_length(
    day: date, start: datetime, end: datetime, hours: int
) -> None:
    """M1-T05: a local day is 23/24/25 h long, bracketed from local midnight.

    Assuming a flat 24 h here is what would let one night be counted on two dates
    (see `test_dst_day_length_does_not_double_count_a_night`).
    """
    assert local_day_bounds_utc(day, STOCKHOLM) == (start, end)
    assert end - start == timedelta(hours=hours)


def test_dst_day_length_does_not_double_count_a_night(db: Session) -> None:
    """M1-T05: on the 23 h spring-forward day a night belongs to exactly one date.

    A sleep ending 2026-03-30 00:30 local (= 2026-03-29 22:30 UTC) falls *after* the
    23 h day 2026-03-29 ends at 22:00 UTC. Bracket the day as a flat 24 h instead and
    this sleep is returned as the night sleep for both the 29th and the 30th.
    """
    sleep = make_sleep(
        db,
        start=local(2026, 3, 29, 23, 0),
        end=local(2026, 3, 30, 0, 30),
        source_external_id="m1t05-dst-night",
    )

    assert night_sleep_for_date(db, date(2026, 3, 29), TZ) is None
    selected = night_sleep_for_date(db, date(2026, 3, 30), TZ)
    assert selected is not None and selected.id == sleep.id


def test_a_sleep_ending_at_local_midnight_belongs_to_one_day_only(db: Session) -> None:
    """M1-T05: the day bounds are half-open, so a midnight boundary isn't double-counted.

    WHOOP really does emit sessions ending exactly on the hour. With inclusive upper
    bounds this session would be the night sleep for both dates; with an exclusive lower
    bound, for neither.
    """
    sleep = make_sleep(
        db,
        start=local(2026, 5, 20, 16, 0),
        end=local(2026, 5, 21, 0, 0),
        source_external_id="m1t05-midnight",
    )

    assert night_sleep_for_date(db, date(2026, 5, 20), TZ) is None
    selected = night_sleep_for_date(db, date(2026, 5, 21), TZ)
    assert selected is not None and selected.id == sleep.id


# --------------------------------------------------------------------------
# M1-T06 — recovery attribution
# --------------------------------------------------------------------------
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

    assert attribute_recovery(recovery, db, TZ) == date(2026, 7, 15)


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
    """M1-T06: a dangling or absent sleep_id falls back to the local date of recorded_at.

    `recorded_at` is chosen to *cross* midnight in UTC — 00:30 local on the 20th is
    22:30 UTC on the 19th — so the fallback has to convert. A same-day timestamp would
    pass just as well under plain UTC truncation and prove nothing.
    """
    recovery = make_recovery(
        db,
        sleep_id=sleep_id,
        recorded_at=local(2026, 7, 20, 0, 30),
        source_external_id=external_id,
    )

    assert attribute_recovery(recovery, db, TZ) == date(2026, 7, 20)


def test_recovery_does_not_follow_a_sleep_id_from_another_source(db: Session) -> None:
    """M1-T06: the sleep lookup is scoped to the recovery's own source.

    `source_external_id` is only unique *within* a source, so once a second wearable
    lands (Oura, HealthKit) an id collision across sources would otherwise attribute a
    recovery to a different device's night. Here the only matching id belongs to another
    source, so the recovery must fall back to `recorded_at`.
    """
    make_sleep(
        db,
        end=local(2026, 7, 25, 7, 0),
        source="oura",
        source_external_id="m1t06-collide",
    )
    recovery = make_recovery(
        db,
        sleep_id="m1t06-collide",
        recorded_at=local(2026, 7, 28, 9, 0),
        source_external_id="m1t06-recovery-cross-source",
    )

    assert attribute_recovery(recovery, db, TZ) == date(2026, 7, 28)


# --------------------------------------------------------------------------
# M1-T07 — the start-date rule
# --------------------------------------------------------------------------
def test_workout_and_cycle_attribute_to_their_start_date(db: Session) -> None:
    """M1-T07: a workout/cycle starting 2026-08-11 23:50 local belongs to 2026-08-11.

    The catalog uses 2026-06-10; moved here so no fixture row lands on M2-T01's golden
    day (TEST_SPEC deviation #5). 23:50 local is 21:50 UTC — the same date either way —
    so a second assertion covers a start that crosses midnight in UTC and would come out
    a day early under plain truncation.
    """
    workout = make_workout(
        db,
        start=local(2026, 8, 11, 23, 50),
        end=local(2026, 8, 12, 0, 50),
        source_external_id="m1t07-workout",
    )
    cycle = make_cycle(
        db,
        start=local(2026, 8, 11, 23, 50),
        end=local(2026, 8, 12, 12, 0),
        source_external_id="m1t07-cycle",
    )

    assert event_local_date(workout.start, TZ) == date(2026, 8, 11)
    assert event_local_date(cycle.start, TZ) == date(2026, 8, 11)
    # 00:30 local on the 12th is 22:30 UTC on the 11th: conversion, not truncation.
    assert event_local_date(local(2026, 8, 12, 0, 30), TZ) == date(2026, 8, 12)


# --------------------------------------------------------------------------
# M1-T08 — the night window
# --------------------------------------------------------------------------
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

    window = night_window(db, date(2026, 9, 10), TZ)

    assert window is not None
    start, end = window
    # The bounds are the sleep's own instants. Asserting them exactly is what stops the
    # window being silently narrowed: these four readings sit well clear of 23:00/07:00,
    # so a window hours too short would still select exactly two rows.
    assert (start, end) == (as_utc(local(2026, 9, 9, 23, 0)), as_utc(local(2026, 9, 10, 7, 0)))

    readings = db.scalars(
        select(AirQualityReading)
        .where(
            AirQualityReading.source_external_id.like("m1t08-air-%"),
            AirQualityReading.recorded_at >= start,
            AirQualityReading.recorded_at <= end,
        )
        .order_by(AirQualityReading.recorded_at)
    ).all()

    assert len(readings) == 2
    assert [r.id for r in readings] == [inside_early.id, inside_late.id]
    assert {r.eco2_ppm for r in readings} == {900.0, 1000.0}
    assert outside_before.id not in {r.id for r in readings}
    assert outside_after.id not in {r.id for r in readings}


def test_night_window_is_inclusive_of_both_bounds(db: Session) -> None:
    """M1-T08: readings exactly at the sleep's start and end count as inside the night.

    D1.5a says "between … start and end" without settling the boundary, so `night_window`
    settles it as inclusive. M2's rollup must compare the same way — otherwise two
    night-air aggregates over the same night disagree.
    """
    make_sleep(
        db,
        start=local(2026, 9, 15, 23, 0),
        end=local(2026, 9, 16, 7, 0),
        source_external_id="m1t08-boundary-night",
    )
    at_start = make_air_reading(
        db, recorded_at=local(2026, 9, 15, 23, 0), source_external_id="m1t08-edge-2300"
    )
    at_end = make_air_reading(
        db, recorded_at=local(2026, 9, 16, 7, 0), source_external_id="m1t08-edge-0700"
    )

    window = night_window(db, date(2026, 9, 16), TZ)

    assert window is not None
    start, end = window
    readings = db.scalars(
        select(AirQualityReading).where(
            AirQualityReading.source_external_id.like("m1t08-edge-%"),
            AirQualityReading.recorded_at >= start,
            AirQualityReading.recorded_at <= end,
        )
    ).all()

    assert {r.id for r in readings} == {at_start.id, at_end.id}


def test_night_window_is_none_without_a_sleep(db: Session) -> None:
    """M1-T08: with no sleep session for the date the night window is None."""
    assert night_window(db, date(2026, 9, 20), TZ) is None
