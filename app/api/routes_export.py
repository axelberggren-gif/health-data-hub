"""Export endpoints: full canonical dataset as JSON or a CSV zip."""

from __future__ import annotations

import io

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..export import exporter

router = APIRouter(prefix="/export", tags=["export"])


@router.get("/json")
def export_json(db: Session = Depends(get_db)) -> JSONResponse:
    return JSONResponse(exporter.export_json(db))


@router.get("/csv")
def export_csv(db: Session = Depends(get_db)) -> StreamingResponse:
    payload = exporter.export_csv_zip(db)
    return StreamingResponse(
        io.BytesIO(payload),
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=health_export.csv.zip"},
    )
