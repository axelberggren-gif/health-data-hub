"""Shared FastAPI dependencies for the HTTP layer.

`require_token` is the single auth wall described in the V1 tech spec (D6). It is
deliberately minimal — one shared secret for one user on one laptop — but it exists from
day one so that no route ever ships unauthenticated *by design*. When hosting moves off
localhost this is the one place that upgrades to real sessions.
"""

from __future__ import annotations

import secrets

from fastapi import Cookie, Header, HTTPException, status

from ..config import get_settings

#: Cookie the PWA stores the token in, so the phone doesn't re-send a header every time.
APP_TOKEN_COOKIE = "app_token"


def _bearer(authorization: str | None) -> str | None:
    """The token out of an `Authorization: Bearer <token>` header, if it is one."""
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer":
        return None
    return value.strip() or None


def require_token(
    authorization: str | None = Header(default=None),
    app_token: str | None = Cookie(default=None, alias=APP_TOKEN_COOKIE),
) -> None:
    """Reject callers that don't present `Settings.app_token`.

    No-op when `app_token` is empty — that is the documented local-dev default, not an
    oversight. The token is compared with `compare_digest` (constant time) and is never
    logged or echoed back in the response.
    """
    expected = get_settings().app_token
    if not expected:
        return

    presented = _bearer(authorization) or app_token
    if presented is None or not secrets.compare_digest(presented, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid app token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
