"""Mill-specific endpoints (diagnostics that don't fit the generic sync API)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..sources.registry import get_source

router = APIRouter(prefix="/mill", tags=["mill"])


@router.get("/diagnose")
def diagnose(db: Session = Depends(get_db)) -> dict:
    """Dump raw Mill sensor + statistics payloads.

    Use this to see exactly what the cloud returns for your sensor — especially
    whether ``/statistics`` carries air-quality history — so the backfill
    mapping in ``sources/mill/history.py`` can be confirmed or extended.
    """
    source = get_source("mill_sense", db)
    diagnose_fn = getattr(source, "diagnose", None)
    if diagnose_fn is None:
        raise HTTPException(501, "mill_sense source has no diagnose()")
    try:
        return diagnose_fn()
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc
