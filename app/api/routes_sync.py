"""Trigger backfill / incremental sync for a registered source."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..sources.base import SyncResult
from ..sources.registry import available_sources, get_source

router = APIRouter(prefix="/sync", tags=["sync"])


@router.get("/sources")
def list_sources() -> dict:
    return {"sources": available_sources()}


@router.post("/{source}/backfill")
def backfill(
    source: str,
    days: int = Query(30, ge=1, le=3650, description="How many days back to pull"),
    db: Session = Depends(get_db),
) -> SyncResult:
    src = _resolve(source, db)
    start = datetime.now(UTC) - timedelta(days=days)
    try:
        return src.backfill(start)
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/{source}/incremental")
def incremental(source: str, db: Session = Depends(get_db)) -> SyncResult:
    src = _resolve(source, db)
    try:
        return src.sync_incremental()
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc


def _resolve(source: str, db: Session):
    try:
        return get_source(source, db)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
