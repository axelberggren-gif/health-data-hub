"""Manual input as a source (docs/specs/TEST_SPEC_V1.md, M3 — decision D3 of the V1 spec).

The daily log is not a special case bolted onto the API: it is a `HealthDataSource` like
WHOOP or Mill, and its writes go through the same `upsert()` on the same identity key. What
makes it different is only *how* the data arrives — a POST instead of a poll — so
`backfill()` / `sync_incremental()` are no-ops.

Identity is what these tests really pin: a check-in keys on its local date, so submitting
the form twice edits one row instead of stacking two, and an intake event keys on a
client-generated UUID, so a phone that retries a request on a flaky connection does not
double-log a supplement.
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import uuid4

from sqlalchemy import func, select

from app.models import CheckinDaily, IntakeEvent
from app.sources.base import HealthDataSource, SyncResult
from app.sources.registry import available_sources, get_source
from tests.factories import HOME_TZ


def _count(db, model) -> int:
    db.rollback()  # drop this session's snapshot: the route wrote on its own connection
    return db.execute(select(func.count()).select_from(model)).scalar_one()


def _one(db, model):
    db.rollback()
    return db.execute(select(model)).scalars().one()


def test_checkin_upserts_by_date(clean_db, client) -> None:
    """M3-T01: two posts for the same date edit one row, keyed `checkin:<date>`."""
    today = datetime.now(HOME_TZ).date()

    first = client.post("/log/checkin", json={"mood": 4, "energy": 3, "alcohol_units": 1.0})
    assert first.status_code == 200

    row = _one(clean_db, CheckinDaily)
    assert row.source == "manual"
    assert row.source_external_id == f"checkin:{today.isoformat()}"
    assert row.date == today
    assert (row.mood, row.energy, row.alcohol_units) == (4, 3, 1.0)

    second = client.post("/log/checkin", json={"mood": 2})
    assert second.status_code == 200

    assert _count(clean_db, CheckinDaily) == 1
    row = _one(clean_db, CheckinDaily)
    assert row.mood == 2
    # Upsert semantics: fields the second request did not mention keep their values.
    assert (row.energy, row.alcohol_units) == (3, 1.0)


def test_checkin_writes_the_requested_date(clean_db, client) -> None:
    """M3-T01: `?date=` targets a past day instead of today."""
    response = client.post("/log/checkin?date=2026-07-05", json={"mood": 5})
    assert response.status_code == 200

    row = _one(clean_db, CheckinDaily)
    assert row.date == date(2026, 7, 5)
    assert row.source_external_id == "checkin:2026-07-05"


def test_checkin_rejects_out_of_range_values(client) -> None:
    """M3-T02: the 1–5 scales and a non-negative alcohol count are enforced at the edge."""
    assert client.post("/log/checkin", json={"mood": 0}).status_code == 422
    assert client.post("/log/checkin", json={"mood": 6}).status_code == 422
    assert client.post("/log/checkin", json={"alcohol_units": -1.0}).status_code == 422


def test_checkin_accepts_an_empty_body(clean_db, client) -> None:
    """M3-T02: every field is optional; an empty body still keys a row to the date."""
    assert client.post("/log/checkin", json={}).status_code == 200

    row = _one(clean_db, CheckinDaily)
    assert row.date == datetime.now(HOME_TZ).date()
    assert row.mood is None


def test_intake_is_idempotent_per_client_id(clean_db, client) -> None:
    """M3-T03: the same client UUID writes one row; a different UUID writes another."""
    client_id = str(uuid4())
    body = {"client_id": client_id, "name": "magnesium", "kind": "supplement", "dose": 300.0}

    assert client.post("/log/intake", json=body).status_code == 200
    assert client.post("/log/intake", json=body).status_code == 200
    assert _count(clean_db, IntakeEvent) == 1

    assert client.post("/log/intake", json={**body, "client_id": str(uuid4())}).status_code == 200
    assert _count(clean_db, IntakeEvent) == 2


def test_intake_requires_a_client_id(client) -> None:
    """M3-T03: without the idempotency key the request is refused, not guessed at."""
    response = client.post("/log/intake", json={"name": "magnesium", "kind": "supplement"})
    assert response.status_code == 422


def test_manual_source_honors_the_seam(clean_db) -> None:
    """M3-T08: it resolves through the registry and its sync methods do nothing."""
    source = get_source("manual", clean_db)

    assert isinstance(source, HealthDataSource)
    assert source.name == "manual"
    assert source.capabilities() == {"checkin", "intake"}
    assert "manual" in available_sources()

    before = (_count(clean_db, CheckinDaily), _count(clean_db, IntakeEvent))
    for result in (source.backfill(datetime.now(HOME_TZ)), source.sync_incremental()):
        assert isinstance(result, SyncResult)
        assert result.source == "manual"
        assert result.counts == {}
    assert (_count(clean_db, CheckinDaily), _count(clean_db, IntakeEvent)) == before
