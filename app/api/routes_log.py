"""The daily log: the owner's own input (tech spec D3, A3/A5/A10).

These routes are thin on purpose. They validate the payload, resolve the local date, and
hand the values to the `manual` source — the mapping and the idempotent write live there,
so the daily log obeys exactly the same seam and the same identity rule as WHOOP or Mill.

Behind the shared-token wall like every other data route (D6).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Body, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..sources.manual.source import ManualSource
from .deps import require_token

router = APIRouter(prefix="/log", tags=["log"], dependencies=[Depends(require_token)])


class CheckinIn(BaseModel):
    """The daily check-in. Every field is optional — a partial answer is a real answer.

    Only the fields actually present in the request are written, so posting `{"mood": 2}`
    in the evening corrects the morning's mood without erasing anything else logged today.
    """

    model_config = ConfigDict(extra="forbid")

    mood: int | None = Field(default=None, ge=1, le=5)
    energy: int | None = Field(default=None, ge=1, le=5)
    stress: int | None = Field(default=None, ge=1, le=5)
    soreness: int | None = Field(default=None, ge=1, le=5)
    alcohol_units: float | None = Field(default=None, ge=0)
    last_caffeine_at: datetime | None = None
    note: str | None = Field(default=None, max_length=2000)


class IntakeIn(BaseModel):
    """One supplement / vitamin / medication event.

    `client_id` is the idempotency key and is required: the phone posts these over a
    connection that drops, and only the client knows whether a request is a retry.
    """

    model_config = ConfigDict(extra="forbid")

    client_id: UUID
    name: str = Field(min_length=1, max_length=200)
    kind: Literal["vitamin", "supplement", "medication"]
    ts: datetime | None = None
    dose: float | None = Field(default=None, ge=0)
    unit: str | None = Field(default=None, max_length=50)


def _today_local() -> date:
    return datetime.now(ZoneInfo(get_settings().home_timezone)).date()


def _written(row: Any, created: bool) -> dict:
    return {"id": row.id, "source_external_id": row.source_external_id, "created": created}


@router.post("/checkin")
def checkin(
    payload: CheckinIn | None = Body(default=None),
    day: date | None = Query(default=None, alias="date"),
    db: Session = Depends(get_db),
) -> dict:
    """Upsert the check-in for today, or for `?date=YYYY-MM-DD`."""
    values = (payload or CheckinIn()).model_dump(exclude_unset=True)
    row, created = ManualSource(db).record_checkin(day or _today_local(), values)
    db.commit()
    return _written(row, created)


@router.post("/intake")
def intake(payload: IntakeIn, db: Session = Depends(get_db)) -> dict:
    """Append an intake event, idempotent on the caller's `client_id`."""
    values = payload.model_dump(exclude_unset=True, exclude={"client_id"})
    row, created = ManualSource(db).record_intake(str(payload.client_id), values)
    db.commit()
    return _written(row, created)
