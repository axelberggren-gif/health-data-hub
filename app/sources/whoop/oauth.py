"""WHOOP OAuth2 authorization-code helpers (RFC-6749)."""

from __future__ import annotations

from urllib.parse import urlencode

import httpx

from ...config import get_settings

settings = get_settings()


def build_authorize_url(state: str) -> str:
    params = {
        "response_type": "code",
        "client_id": settings.whoop_client_id,
        "redirect_uri": settings.whoop_redirect_uri,
        "scope": settings.whoop_scopes,
        "state": state,
    }
    return f"{settings.whoop_authorize_url}?{urlencode(params)}"


def exchange_code(code: str) -> dict:
    """Exchange an authorization code for access/refresh tokens."""
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.whoop_redirect_uri,
        "client_id": settings.whoop_client_id,
        "client_secret": settings.whoop_client_secret,
    }
    resp = httpx.post(settings.whoop_token_url, data=data, timeout=30)
    resp.raise_for_status()
    return resp.json()


def refresh_tokens(refresh_token: str) -> dict:
    """Use a refresh token to obtain a new access token (rotates refresh)."""
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": settings.whoop_client_id,
        "client_secret": settings.whoop_client_secret,
        "scope": "offline",
    }
    resp = httpx.post(settings.whoop_token_url, data=data, timeout=30)
    resp.raise_for_status()
    return resp.json()
