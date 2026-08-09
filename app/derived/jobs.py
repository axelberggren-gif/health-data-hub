"""The daily derivation job (tech spec §5) — the derived layer's only write path.

Design constraints that shaped this:

* **The host is a laptop that sleeps.** The job may never assume it ran yesterday, so every
  run recomputes a *window* of days rather than appending one, and `catch_up_if_stale` fills
  a gap of any size on startup. Missed days heal themselves.
* **Late data is normal.** A WHOOP sync at noon changes yesterday's numbers, so recomputing
  a day must be free of consequences — which it is, because every write is an `upsert()` on
  a deterministic key.
* **The reference day is the newest day with data, not the calendar date.** At 07:00 there
  may be no data for today yet; judging "today" against its baseline then would compare a
  blank day to a month of real ones.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import DailySummary
from ..sync.orchestrator import upsert
from . import DERIVED_SOURCE
from .baselines import recompute_baselines
from .dates import home_tz
from .flags import apply_flags
from .rollup import summarize_date

logger = logging.getLogger("derived.jobs")

#: Default window. Wide enough that a few missed days heal on the next run, narrow enough
#: that the job stays cheap enough to run on every startup.
DEFAULT_DAYS_BACK = 7

#: A derivation is stale once it does not even cover yesterday (tech spec §5, "> 24 h old").
STALE_AFTER_DAYS = 1


@dataclass
class DerivationReport:
    """Per-step counts, mirroring `SyncResult` so the API surface feels the same."""

    days_back: int
    counts: dict[str, int] = field(default_factory=dict)
    dates: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def add(self, step: str, n: int) -> None:
        self.counts[step] = self.counts.get(step, 0) + n

    def as_dict(self) -> dict:
        return {
            "days_back": self.days_back,
            "counts": self.counts,
            "dates": self.dates,
            "notes": self.notes,
        }


def local_today() -> date:
    """Today's date in the configured home timezone."""
    return datetime.now(home_tz()).date()


def newest_summary_date(db: Session) -> date | None:
    """The most recent local date that has a `daily_summary` row."""
    return db.execute(
        select(DailySummary.date).order_by(DailySummary.date.desc()).limit(1)
    ).scalar_one_or_none()


def run_daily_derivation(
    db: Session,
    days_back: int = DEFAULT_DAYS_BACK,
    *,
    today: date | None = None,
) -> DerivationReport:
    """Recompute the last `days_back` local dates, then baselines, then flags.

    `today` pins the last date of the window; it defaults to the local today and is passed
    explicitly to backfill a historical window (and by the tests, which need fixed dates).
    Commits once at the end so a failure part-way through leaves nothing half-derived.
    """
    end = today or local_today()
    window = [end - timedelta(days=offset) for offset in range(days_back - 1, -1, -1)]
    report = DerivationReport(days_back=days_back)

    for day in window:
        values = summarize_date(db, day)
        if values is None:
            report.add("skipped_no_data", 1)
            continue
        upsert(
            db,
            DailySummary,
            source=DERIVED_SOURCE,
            source_external_id=day.isoformat(),
            values={"date": day, **values},
        )
        report.add("daily_summary", 1)
        report.dates.append(day.isoformat())
    db.flush()

    reference = newest_summary_date(db) or end
    report.add("baseline", recompute_baselines(db, reference))
    report.add("flags", len(apply_flags(db, reference)))
    report.notes.append(f"flags evaluated for {reference.isoformat()}")

    db.commit()
    logger.info("derivation done: %s", report.counts)
    return report


def catch_up_if_stale(
    db: Session, *, days_back: int = DEFAULT_DAYS_BACK
) -> DerivationReport | None:
    """Derive on startup iff the newest summary is stale. Returns `None` when it isn't.

    The window is widened to cover the whole gap, so a laptop that was shut for two weeks
    still ends up with every day it has data for.
    """
    today = local_today()
    newest = newest_summary_date(db)
    if newest is not None and newest >= today - timedelta(days=STALE_AFTER_DAYS):
        return None

    if newest is not None:
        days_back = max(days_back, (today - newest).days + 1)
    logger.info("derived data is stale (newest=%s); catching up %s days", newest, days_back)
    return run_daily_derivation(db, days_back=days_back, today=today)
