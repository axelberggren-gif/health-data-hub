"""App auth (see docs/specs/TEST_SPEC_V1.md, M0 — decision D6 of the V1 tech spec).

A single shared bearer token guards the data routes. Empty token => auth disabled, which
is the local-dev default; set it and every protected prefix must refuse anonymous callers.

**Extend, don't duplicate:** as `/dashboard`, `/log` and `/insights` land in later
milestones, add their prefixes to `PROTECTED_ROUTES` — M0-T04 is parametrized over it and
M3-T09 / M6-T05 are satisfied by that extension.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings

TOKEN = "test-token-123"

# (method, path) of one representative route per protected router prefix.
PROTECTED_ROUTES = [
    ("GET", "/export/json"),
]


@pytest.fixture
def make_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[object]:
    """Build a TestClient whose app sees a specific APP_TOKEN value."""

    def _make(token: str) -> TestClient:
        monkeypatch.setenv("APP_TOKEN", token)
        get_settings.cache_clear()
        from app.main import app

        return TestClient(app)

    yield _make
    get_settings.cache_clear()


@pytest.mark.parametrize(("method", "path"), PROTECTED_ROUTES)
def test_auth_disabled_when_token_unset(make_client, method: str, path: str) -> None:
    """M0-T03: with an empty app_token, protected routes are open (dev default)."""
    with make_client("") as client:
        response = client.request(method, path)

    assert response.status_code != 401


@pytest.mark.parametrize(("method", "path"), PROTECTED_ROUTES)
def test_auth_rejects_missing_and_wrong_tokens(make_client, method: str, path: str) -> None:
    """M0-T04: with app_token set, only the exact bearer token is accepted."""
    with make_client(TOKEN) as client:
        assert client.request(method, path).status_code == 401
        assert (
            client.request(method, path, headers={"Authorization": "Bearer wrong"}).status_code
            == 401
        )
        assert (
            client.request(method, path, headers={"Authorization": f"Bearer {TOKEN}"}).status_code
            != 401
        )


@pytest.mark.parametrize(("method", "path"), PROTECTED_ROUTES)
def test_auth_accepts_the_token_cookie(make_client, method: str, path: str) -> None:
    """M0-T04: the PWA's stored cookie is an accepted carrier for the same token."""
    with make_client(TOKEN) as client:
        client.cookies.set("app_token", TOKEN)
        assert client.request(method, path).status_code != 401

        client.cookies.set("app_token", "wrong")
        assert client.request(method, path).status_code == 401


def test_public_routes_stay_open(make_client) -> None:
    """M0-T04: the health check and root stay reachable even with auth enabled."""
    with make_client(TOKEN) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/").status_code == 200
