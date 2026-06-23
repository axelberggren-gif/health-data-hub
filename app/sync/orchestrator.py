"""Idempotent persistence helpers shared by all sources.

``upsert`` keys on ``(source, source_external_id)`` so re-running a sync never
duplicates rows. Cursors track the incremental watermark per source/resource.
Callers are responsible for committing the session.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import SyncCursor


def upsert(
    db: Session,
    model: type,
    *,
    source: str,
    source_external_id: str,
    values: dict[str, Any],
) -> tuple[Any, bool]:
    """Insert or update a row identified by (source, source_external_id)."""
    obj = db.execute(
        select(model).where(
            # SQLAlchemy maps these columns dynamically; mypy can't see them on `type`.
            model.source == source,  # type: ignore[attr-defined]
            model.source_external_id == source_external_id,  # type: ignore[attr-defined]
        )
    ).scalar_one_or_none()
    created = obj is None
    if obj is None:
        obj = model(source=source, source_external_id=source_external_id)
        db.add(obj)
    for key, value in values.items():
        setattr(obj, key, value)
    return obj, created


def get_cursor(db: Session, source: str, resource: str) -> datetime | None:
    row = db.execute(
        select(SyncCursor).where(SyncCursor.source == source, SyncCursor.resource == resource)
    ).scalar_one_or_none()
    return row.last_synced_at if row else None


def set_cursor(db: Session, source: str, resource: str, ts: datetime) -> None:
    row = db.execute(
        select(SyncCursor).where(SyncCursor.source == source, SyncCursor.resource == resource)
    ).scalar_one_or_none()
    if row is None:
        db.add(SyncCursor(source=source, resource=resource, last_synced_at=ts))
    else:
        row.last_synced_at = ts
