"""Check-in and weather reaching the daily summary (docs/specs/TEST_SPEC_V1.md, M3).

M3-T10 / M3-T11 are additions to the catalog, not cases from it — see the note under M3
there. The catalog stops at "the row is written to `checkin_daily` / `weather_daily`", but
`daily_summary` already reserves columns for both (tech spec §4, "filled by the manual /
open_meteo source in M3"), and everything downstream — baselines, the correlation engine in
M4, the brief in M5 — reads the summary, not the source tables. Without this wiring M3
would land data that nothing can ever see.

The asymmetry in M3-T11 is the load-bearing part: a check-in is an act, so it makes a day
worth summarizing; weather happens whether or not the owner was measured, so weather alone
must never manufacture a summary row (tech spec §5.1).
"""

from __future__ import annotations

from datetime import date

from app.derived.rollup import summarize_date
from tests.factories import (
    local,
    make_checkin,
    make_recovery,
    make_sleep,
    make_weather,
)


def test_checkin_and_weather_reach_the_summary(clean_db) -> None:
    """M3-T10: a day's check-in and weather land in the daily-summary columns."""
    day = date(2026, 7, 20)
    make_sleep(clean_db, start=local(2026, 7, 19, 23, 0), end=local(2026, 7, 20, 7, 0))
    make_recovery(clean_db, recorded_at=local(2026, 7, 20, 7, 5))
    make_checkin(
        clean_db,
        day=day,
        mood=4,
        energy=2,
        stress=5,
        soreness=3,
        alcohol_units=2.5,
        last_caffeine_at=local(2026, 7, 20, 16, 30),
    )
    make_weather(
        clean_db,
        day=day,
        temp_min_c=13.5,
        temp_max_c=24.0,
        daylight_seconds=61200,
        sunrise=local(2026, 7, 20, 4, 12),
        sunset=local(2026, 7, 20, 21, 12),
    )

    values = summarize_date(clean_db, day)
    assert values is not None

    assert values["checkin_mood"] == 4
    assert values["checkin_energy"] == 2
    assert values["checkin_stress"] == 5
    assert values["checkin_soreness"] == 3
    assert values["alcohol_units"] == 2.5
    assert values["caffeine_after_14"] is True

    assert values["weather_temp_min_c"] == 13.5
    assert values["weather_temp_max_c"] == 24.0
    assert values["daylight_seconds"] == 61200
    assert values["sunrise"] is not None and values["sunset"] is not None


def test_caffeine_flag_reflects_the_local_clock(clean_db) -> None:
    """M3-T10: `caffeine_after_14` is derived from the local hour, and stays null if unknown."""
    morning = date(2026, 7, 21)
    make_sleep(clean_db, start=local(2026, 7, 20, 23, 0), end=local(2026, 7, 21, 7, 0))
    make_checkin(clean_db, day=morning, last_caffeine_at=local(2026, 7, 21, 9, 0))
    assert summarize_date(clean_db, morning)["caffeine_after_14"] is False

    unknown = date(2026, 7, 22)
    make_sleep(clean_db, start=local(2026, 7, 21, 23, 0), end=local(2026, 7, 22, 7, 0))
    make_checkin(clean_db, day=unknown, last_caffeine_at=None)
    assert summarize_date(clean_db, unknown)["caffeine_after_14"] is None


def test_a_checkin_alone_is_enough_for_a_summary(clean_db) -> None:
    """M3-T11: logging how you feel makes a day worth summarizing, with nothing else."""
    day = date(2026, 7, 23)
    make_checkin(clean_db, day=day, mood=3)

    values = summarize_date(clean_db, day)
    assert values is not None
    assert values["checkin_mood"] == 3
    assert values["recovery_score"] is None
    assert values["readiness_score"] is None  # no recovery => never invented


def test_weather_alone_does_not_create_a_summary(clean_db) -> None:
    """M3-T11: weather decorates a measured day; it never manufactures one."""
    day = date(2026, 7, 24)
    make_weather(clean_db, day=day, temp_min_c=10.0, temp_max_c=18.0)

    assert summarize_date(clean_db, day) is None
