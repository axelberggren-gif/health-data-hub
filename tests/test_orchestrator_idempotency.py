"""Guards INVARIANT #2: persistence is idempotent on ``(source, source_external_id)``.

Re-running a sync must never duplicate rows. This is enforced two ways, both tested:
  1. ``orchestrator.upsert()`` updates the existing row instead of inserting a new one.
  2. The DB ``UniqueConstraint`` backs it up if anyone bypasses upsert with a raw insert.
"""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import RecoveryDaily
from app.sync.orchestrator import upsert


def test_upsert_updates_not_duplicates(db):
    obj1, created1 = upsert(
        db,
        RecoveryDaily,
        source="test",
        source_external_id="rec-1",
        values={"recovery_score": 50.0},
    )
    db.commit()
    assert created1 is True

    # Same identity, new values -> must UPDATE the same row, not insert a second.
    obj2, created2 = upsert(
        db,
        RecoveryDaily,
        source="test",
        source_external_id="rec-1",
        values={"recovery_score": 80.0},
    )
    db.commit()
    assert created2 is False
    assert obj1.id == obj2.id

    rows = db.scalars(
        select(RecoveryDaily).where(
            RecoveryDaily.source == "test",
            RecoveryDaily.source_external_id == "rec-1",
        )
    ).all()
    assert len(rows) == 1
    assert rows[0].recovery_score == 80.0


def test_raw_duplicate_insert_is_rejected_by_unique_constraint(db):
    db.add(RecoveryDaily(source="dup", source_external_id="rec-2"))
    db.commit()

    db.add(RecoveryDaily(source="dup", source_external_id="rec-2"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
