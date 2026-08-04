"""Derived-layer routes: recompute daily summaries, baselines and flags on demand.

The job also runs on a schedule (06:00 local) and catches up on startup, so this endpoint is
the manual "refresh now" the dashboard offers after a fresh WHOOP sync — not the primary
trigger. It is behind the shared-token wall like every other data route (D6).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..derived.jobs import DEFAULT_DAYS_BACK, run_daily_derivation
from .deps import require_token

router = APIRouter(prefix="/derived", tags=["derived"], dependencies=[Depends(require_token)])

#: Two years is plenty for a personal history and keeps an accidental huge request bounded.
MAX_DAYS_BACK = 730


@router.post("/run")
def run(
    days_back: int = Query(default=DEFAULT_DAYS_BACK, ge=1, le=MAX_DAYS_BACK),
    db: Session = Depends(get_db),
) -> dict:
    """Recompute the last `days_back` local dates and return per-step counts."""
    try:
        report = run_daily_derivation(db, days_back=days_back)
    except Exception as exc:  # surface a clean error instead of a bare 500
        raise HTTPException(status_code=500, detail=f"Derivation failed: {exc}") from exc
    return report.as_dict()
