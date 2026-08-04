"""Settings defaults (see docs/specs/TEST_SPEC_V1.md, M0).

The app must boot with **no** configuration at all: every V1 setting has a safe default,
and the ones that gate a feature (LLM key, coordinates, auth token) default to "off"
rather than to a guess.
"""

from __future__ import annotations

import pytest

from app.config import Settings


@pytest.fixture
def isolated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove every env var that maps to a Settings field, so defaults are observable."""
    import os

    field_names = {name.upper() for name in Settings.model_fields}
    for key in list(os.environ):
        if key.upper() in field_names:
            monkeypatch.delenv(key, raising=False)


@pytest.mark.usefixtures("isolated_env")
def test_settings_defaults_are_safe() -> None:
    """M0-T02: with no env vars (and no .env), the V1 settings hold their safe defaults."""
    settings = Settings(_env_file=None)

    assert settings.home_timezone == "Europe/Stockholm"
    assert settings.home_lat == 0.0
    assert settings.home_lon == 0.0
    assert settings.app_token == ""
    assert settings.anthropic_api_key == ""
    assert settings.llm_provider == "claude"
    assert settings.llm_daily_token_cap == 50_000
    assert settings.llm_model  # a concrete default model, not empty


def test_app_boots_with_default_settings(client) -> None:
    """M0-T02: the app still boots and serves /health with defaults in place."""
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
