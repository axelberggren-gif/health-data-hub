"""ManualSource — the daily check-in (A3/A5) and the intake log (A10).

Two identity rules carry the whole design:

* A **check-in keys on its local date**, so the form is editable. Answering in the morning
  and correcting in the evening leaves one row for the day, not two opinions the rollup
  would have to choose between.
* An **intake event keys on a client-generated UUID**. The phone posts these over a
  connection that drops; a retry must not log the same magnesium twice, and the client is
  the only party that knows a retry *is* one.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy.orm import Session

from ...models import CheckinDaily, IntakeEvent
from ...sync.orchestrator import upsert
from ..base import HealthDataSource, SyncResult
from ..localtime import local_midnight_utc

#: Namespaces the check-in key so a date can never collide with another manual resource.
CHECKIN_KEY_PREFIX = "checkin:"


def checkin_key(day: date) -> str:
    """The `source_external_id` of the check-in for a local date."""
    return f"{CHECKIN_KEY_PREFIX}{day.isoformat()}"


class ManualSource(HealthDataSource):
    """The owner's own input. Arrives by POST; there is nothing to poll."""

    name = "manual"

    def __init__(self, db: Session):
        self.db = db

    def capabilities(self) -> set[str]:
        return {"checkin", "intake"}

    # ---- the seam's sync methods: deliberately inert -----------------------
    def backfill(self, start: datetime, end: datetime | None = None) -> SyncResult:
        return self._nothing_to_pull()

    def sync_incremental(self) -> SyncResult:
        return self._nothing_to_pull()

    def _nothing_to_pull(self) -> SyncResult:
        now = datetime.now(UTC)
        return SyncResult(
            source=self.name,
            started_at=now,
            finished_at=now,
            notes=["manual input arrives by POST /log/*; there is nothing to pull"],
        )

    # ---- the real write paths, called by the /log routes -------------------
    def record_checkin(self, day: date, values: dict[str, Any]) -> tuple[CheckinDaily, bool]:
        """Upsert the check-in for `day`. Only the keys in `values` are written.

        Partial by design: `{"mood": 2}` corrects this morning's mood without erasing the
        alcohol count logged last night. The caller commits.
        """
        row, created = upsert(
            self.db,
            CheckinDaily,
            source=self.name,
            source_external_id=checkin_key(day),
            values={"date": day, "recorded_at": local_midnight_utc(day), **values},
        )
        return row, created

    def record_intake(self, client_id: str, values: dict[str, Any]) -> tuple[IntakeEvent, bool]:
        """Upsert one intake event under the client's idempotency key. The caller commits."""
        ts = values.get("ts") or datetime.now(UTC)
        row, created = upsert(
            self.db,
            IntakeEvent,
            source=self.name,
            source_external_id=client_id,
            values={**values, "ts": ts, "recorded_at": ts},
        )
        return row, created
