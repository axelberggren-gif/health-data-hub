"""Reserved-but-empty canonical tables (docs/specs/TEST_SPEC_V1.md, M3-T07).

`biomarker` and `nutrition_entry` ship with no writer, no route and no UI. The point is
purely that the *shape* exists now: adding blood panels or food logging later should be an
adapter plus a form, not a migration scramble against six months of live data.

What must hold today is that they are real canonical tables — present in the metadata and
in the migrated database, and carrying the same `(source, source_external_id)` identity
backstop as every other ingested table (global invariant #2) — and that nothing exposes
them over HTTP yet.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError

from app.db import Base
from app.models import Biomarker, NutritionEntry

RESERVED = (Biomarker, NutritionEntry)


@pytest.mark.parametrize("model", RESERVED, ids=lambda m: m.__tablename__)
def test_reserved_table_is_registered(model) -> None:
    """M3-T07: the table is in `Base.metadata` (and therefore in the migrated schema)."""
    assert model.__tablename__ in Base.metadata.tables


@pytest.mark.parametrize("model", RESERVED, ids=lambda m: m.__tablename__)
def test_reserved_table_has_the_identity_constraint(model) -> None:
    """M3-T07: `(source, source_external_id)` is unique, per global invariant #2."""
    unique_columns = {
        tuple(c.name for c in constraint.columns)
        for constraint in Base.metadata.tables[model.__tablename__].constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("source", "source_external_id") in unique_columns


@pytest.mark.parametrize("model", RESERVED, ids=lambda m: m.__tablename__)
def test_reserved_table_rejects_a_duplicate_key(db, model) -> None:
    """M3-T07: the database itself refuses a second row on the same key.

    Deliberately bypasses `upsert()`: this asserts the backstop that catches anyone who
    does the same by accident.
    """
    external_id = f"reserved-dupe-{model.__tablename__}"
    now = datetime.now(UTC)
    field = "taken_at" if model is Biomarker else "ts"

    for _ in range(2):
        db.add(model(source="manual", source_external_id=external_id, **{field: now}))

    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


@pytest.mark.parametrize("path", ["/log/biomarker", "/log/nutrition"])
def test_reserved_tables_have_no_routes(client, path: str) -> None:
    """M3-T07: reserving a table does not reserve an endpoint — V1 exposes neither."""
    assert client.post(path, json={}).status_code == 404
