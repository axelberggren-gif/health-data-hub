"""WHOOP OAuth endpoints: kick off login and handle the callback."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import WhoopConnection
from ..sources.whoop import oauth

router = APIRouter(prefix="/auth/whoop", tags=["auth"])
settings = get_settings()

# Dev-only in-memory CSRF state store. Replace with signed cookies / Redis
# for multi-process or production deployments.
_PENDING_STATES: set[str] = set()


@router.get("/login")
def login() -> RedirectResponse:
    if not settings.whoop_client_id:
        raise HTTPException(500, "WHOOP_CLIENT_ID is not configured (see .env).")
    state = secrets.token_urlsafe(24)
    _PENDING_STATES.add(state)
    return RedirectResponse(oauth.build_authorize_url(state))


@router.get("/callback")
def callback(
    code: str = Query(...),
    state: str | None = Query(None),
    db: Session = Depends(get_db),
) -> dict:
    if state is None or state not in _PENDING_STATES:
        raise HTTPException(400, "Invalid or expired OAuth state.")
    _PENDING_STATES.discard(state)

    tokens = oauth.exchange_code(code)

    conn = db.execute(select(WhoopConnection).order_by(WhoopConnection.id.desc())).scalars().first()
    if conn is None:
        conn = WhoopConnection(access_token=tokens["access_token"])
        db.add(conn)
    else:
        conn.access_token = tokens["access_token"]
    conn.refresh_token = tokens.get("refresh_token")
    if tokens.get("expires_in"):
        conn.expires_at = datetime.now(UTC) + timedelta(seconds=int(tokens["expires_in"]))
    conn.scope = tokens.get("scope")
    db.commit()

    return {
        "status": "connected",
        "scope": conn.scope,
        "expires_at": conn.expires_at,
        "next": "POST /sync/whoop_api/backfill?days=30",
    }
