"""Background jobs: the Mill Sense poller and the daily derivation tick.

Both are deliberately small asyncio loops (no scheduler dependency) started and stopped by
the FastAPI lifespan. Their per-tick work is blocking (httpx, SQL), so it runs in a worker
thread to keep the event loop free.

Mill Sense poller
-----------------

The Mill cloud returns only the latest reading per device, so we poll on an
interval and let ``AirQualityReading`` rows accumulate — optionally only within
a nightly window so we sample while you sleep. Off by default; enable with
``MILL_POLL_ENABLED=true``.

Derivation tick
---------------

Recomputes the derived layer once a day at ``DERIVED_RUN_HOUR`` local time, and once at
startup if the newest ``daily_summary`` has gone stale. On by default: it is local
computation over data already in the store, and without it a laptop that sleeps through
06:00 would silently stop deriving.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from .config import get_settings
from .db import SessionLocal
from .derived.dates import home_tz
from .derived.jobs import catch_up_if_stale, run_daily_derivation
from .sources.registry import get_source

logger = logging.getLogger("mill.scheduler")

_MIN_INTERVAL_SECONDS = 30


def in_window(hour: int, start: int, end: int) -> bool:
    """Whether ``hour`` falls in [start, end), tolerant of midnight wrap."""
    if start == end:
        return True
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


class MillPoller:
    def __init__(self) -> None:
        settings = get_settings()
        self.interval = max(_MIN_INTERVAL_SECONDS, settings.mill_poll_interval_seconds)
        self.start_hour = settings.mill_poll_start_hour
        self.end_hour = settings.mill_poll_end_hour
        self._task: asyncio.Task | None = None

    def _should_poll_now(self) -> bool:
        if self.start_hour is None or self.end_hour is None:
            return True
        return in_window(datetime.now().hour, self.start_hour, self.end_hour)

    def _poll_once(self) -> None:
        db = SessionLocal()
        try:
            result = get_source("mill_sense", db).sync_incremental()
            logger.info("mill poll ok: counts=%s notes=%s", result.counts, result.notes)
        finally:
            db.close()

    async def _run(self) -> None:
        logger.info(
            "mill poller started (interval=%ss, window=%s-%s)",
            self.interval,
            self.start_hour,
            self.end_hour,
        )
        while True:
            try:
                if self._should_poll_now():
                    await asyncio.to_thread(self._poll_once)
            except asyncio.CancelledError:
                raise
            except Exception:  # never let a bad tick kill the loop
                logger.exception("mill poll tick failed")
            await asyncio.sleep(self.interval)

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None


def maybe_start() -> MillPoller | None:
    """Start the poller iff enabled and credentials are present."""
    settings = get_settings()
    if not settings.mill_poll_enabled:
        return None
    if not (settings.mill_username and settings.mill_password):
        logger.warning(
            "MILL_POLL_ENABLED is set but MILL_USERNAME/MILL_PASSWORD are missing; "
            "poller not started."
        )
        return None
    poller = MillPoller()
    poller.start()
    return poller


# --------------------------------------------------------------------------
# Daily derivation
# --------------------------------------------------------------------------
def seconds_until(hour: int, *, now: datetime, tz: ZoneInfo) -> float:
    """Seconds from ``now`` to the next occurrence of ``hour``:00 local time.

    The target is a wall-clock time, not a fixed 24 h interval, so the tick keeps landing at
    06:00 instead of drifting an hour at each DST change. The *duration* is then measured in
    UTC on purpose: subtracting two datetimes that share a ``tzinfo`` gives Python's naive
    wall-clock difference, which on a 23-hour day would sleep an hour too long.
    """
    local_now = now.astimezone(tz)
    target = local_now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if target <= local_now:
        target += timedelta(days=1)
    return (target.astimezone(UTC) - local_now.astimezone(UTC)).total_seconds()


class DerivationScheduler:
    """Runs the derivation job daily at a local hour, plus a catch-up at startup."""

    def __init__(self) -> None:
        settings = get_settings()
        self.hour = settings.derived_run_hour
        self._task: asyncio.Task | None = None

    def _run_once(self, *, catch_up: bool) -> None:
        db = SessionLocal()
        try:
            report = catch_up_if_stale(db) if catch_up else run_daily_derivation(db)
            if report is None:
                logger.info("derived data is current; no catch-up needed")
            else:
                logger.info("derivation counts=%s notes=%s", report.counts, report.notes)
        finally:
            db.close()

    async def _run(self) -> None:
        logger.info("derivation scheduler started (daily at %02d:00 local)", self.hour)
        try:
            await asyncio.to_thread(self._run_once, catch_up=True)
        except asyncio.CancelledError:
            raise
        except Exception:  # a failed catch-up must not stop the daily tick
            logger.exception("startup derivation catch-up failed")

        tz = home_tz()
        while True:
            await asyncio.sleep(seconds_until(self.hour, now=datetime.now(tz), tz=tz))
            try:
                await asyncio.to_thread(self._run_once, catch_up=False)
            except asyncio.CancelledError:
                raise
            except Exception:  # never let a bad tick kill the loop
                logger.exception("daily derivation tick failed")

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None


def maybe_start_derivation() -> DerivationScheduler | None:
    """Start the derivation scheduler unless it is switched off."""
    if not get_settings().derived_schedule_enabled:
        return None
    scheduler = DerivationScheduler()
    scheduler.start()
    return scheduler
