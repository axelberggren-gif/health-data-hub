"""Export the canonical store to portable JSON or a zip of CSV files.

This is the original "export my WHOOP data" capability — now over the
source-agnostic canonical model, so it covers every source you add later.
"""

from __future__ import annotations

import csv
import io
import json
import zipfile
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import EXPORT_MODELS


def _row_to_dict(obj, json_as_str: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for column in obj.__table__.columns:
        value = getattr(obj, column.name)
        if isinstance(value, (datetime, date)):
            value = value.isoformat()
        elif json_as_str and isinstance(value, (dict, list)):
            value = json.dumps(value)
        out[column.name] = value
    return out


def export_json(db: Session) -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = {}
    for model in EXPORT_MODELS:
        rows = db.execute(select(model)).scalars().all()
        result[model.__tablename__] = [_row_to_dict(r) for r in rows]
    return result


def export_csv_zip(db: Session) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for model in EXPORT_MODELS:
            rows = db.execute(select(model)).scalars().all()
            columns = [c.name for c in model.__table__.columns]
            text = io.StringIO()
            writer = csv.DictWriter(text, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow(_row_to_dict(row, json_as_str=True))
            archive.writestr(f"{model.__tablename__}.csv", text.getvalue())
    return buffer.getvalue()
