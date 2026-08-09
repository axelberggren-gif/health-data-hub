"""The derivation scheduler's wiring (see TEST_SPEC_V1.md, M2-T10 — tech spec §5).

The catch-up behaviour itself is covered in `test_derived_job.py`; what is worth pinning here
is the part that decides *when* to run, because a drifting or silently-disabled tick is how a
derived layer quietly goes stale.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.config import get_settings
from app.scheduler import DerivationScheduler, maybe_start_derivation, seconds_until

TZ = ZoneInfo("Europe/Stockholm")


@pytest.mark.parametrize(
    ("now", "expected_hours"),
    [
        (datetime(2026, 6, 10, 5, 0, tzinfo=TZ), 1.0),  # later today
        (datetime(2026, 6, 10, 6, 0, tzinfo=TZ), 24.0),  # exactly on the hour -> tomorrow
        (datetime(2026, 6, 10, 18, 0, tzinfo=TZ), 12.0),  # after it, so tomorrow
    ],
)
def test_seconds_until_targets_the_next_local_hour(now: datetime, expected_hours: float) -> None:
    """M2-T10: the tick is scheduled against wall-clock 06:00, not a rolling 24 h."""
    assert seconds_until(6, now=now, tz=TZ) == expected_hours * 3600


def test_seconds_until_survives_the_spring_forward_night() -> None:
    """A 23-hour day must still resolve to the next 06:00, not to a crash or 22:00."""
    # 2026-03-29 is the CET->CEST transition; the day is 23 hours long.
    before = datetime(2026, 3, 28, 18, 0, tzinfo=TZ)
    assert seconds_until(6, now=before, tz=TZ) == 11 * 3600  # wall clock, not elapsed time


def test_scheduler_is_disabled_by_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    """M2-T10: the tick can be switched off (which is how this suite stays deterministic)."""
    monkeypatch.setenv("DERIVED_SCHEDULE_ENABLED", "false")
    get_settings.cache_clear()
    try:
        assert maybe_start_derivation() is None
    finally:
        get_settings.cache_clear()


def test_scheduler_reads_its_hour_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """The run hour is configuration, not a literal buried in the loop."""
    monkeypatch.setenv("DERIVED_RUN_HOUR", "4")
    get_settings.cache_clear()
    try:
        assert DerivationScheduler().hour == 4
    finally:
        get_settings.cache_clear()
