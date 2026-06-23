"""Background poller that turns the Mill Sense snapshot API into a time series.

The Mill cloud returns only the latest reading per device, so we poll on an
interval and let ``AirQualityReading`` rows accumulate — optionally only within
a nightly window so we sample while you sleep. Off by default; enable with
``MILL_POLL_ENABLED=true``. Started and stopped by the FastAPI lifespan.

This is a deliberately small asyncio loop (no extra dependency). The per-tick
sync is blocking (httpx + retry sleeps), so it runs in a worker thread to keep
the event loop free.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from .config import get_settings
from .db import SessionLocal
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
