"""Mill cloud authentication.

Mill's consumer cloud (``api.millnorwaycloud.com``) does not use OAuth: a client
signs in with the Mill app *username/password* and receives a short-lived JWT
(``idToken``) plus a ``refreshToken``. We read the token's ``exp`` claim to know
when to refresh, falling back to a conservative TTL when it can't be parsed
(the source also re-authenticates reactively on a 401).
"""

from __future__ import annotations

import base64
import binascii
import json
from datetime import UTC, datetime, timedelta

import httpx

from ...config import get_settings

settings = get_settings()

_DEFAULT_TTL = timedelta(hours=12)  # used only if the JWT exp is unreadable


def _jwt_exp(token: str) -> datetime | None:
    """Best-effort decode of a JWT's ``exp`` claim (no signature check)."""
    try:
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)  # restore padding
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        exp = payload.get("exp")
        return datetime.fromtimestamp(int(exp), tz=UTC) if exp else None
    except (IndexError, ValueError, binascii.Error, json.JSONDecodeError):
        return None


def _normalize(data: dict) -> dict:
    """Shape a sign-in / refresh response into our token dict."""
    token = data.get("idToken") or data.get("access_token") or ""
    expires_at = _jwt_exp(token) or (datetime.now(UTC) + _DEFAULT_TTL)
    return {
        "access_token": token,
        "refresh_token": data.get("refreshToken") or data.get("refresh_token"),
        "expires_at": expires_at,
    }


def sign_in(username: str, password: str) -> dict:
    """Exchange username/password for an idToken + refreshToken."""
    resp = httpx.post(
        f"{settings.mill_api_base}/customer/auth/sign-in",
        json={"login": username, "password": password},
        timeout=30,
    )
    resp.raise_for_status()
    return _normalize(resp.json())


def refresh_tokens(refresh_token: str) -> dict:
    """Use a refresh token to obtain a fresh idToken."""
    resp = httpx.post(
        f"{settings.mill_api_base}/customer/auth/refresh",
        headers={"Authorization": f"Bearer {refresh_token}"},
        timeout=30,
    )
    resp.raise_for_status()
    out = _normalize(resp.json())
    # Mill may not re-issue a refresh token on refresh; keep the existing one.
    if not out["refresh_token"]:
        out["refresh_token"] = refresh_token
    return out
