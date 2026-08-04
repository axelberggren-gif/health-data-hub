"""Application settings, loaded from environment / .env file."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Health Data Hub"
    env: str = "dev"

    # Canonical store. SQLite by default; point at Postgres in production.
    database_url: str = "sqlite:///./health.db"

    # --- App auth (tech spec D6) ---
    # One shared bearer token guards the data routes (/export, and the /dashboard,
    # /log, /insights routes as they land). Empty => auth disabled, which is the
    # local-dev default; set it before the app is reachable from anywhere but
    # localhost. The PWA stores it in an `app_token` cookie.
    app_token: str = ""

    # --- Home location (tech spec D1 / D7) ---
    # `home_timezone` defines the local calendar every derived `date` key uses.
    # The coordinates feed the weather source; 0.0/0.0 => weather stays disabled
    # (an unset location is "off", never a guess).
    home_timezone: str = "Europe/Stockholm"
    home_lat: float = 0.0
    home_lon: float = 0.0

    # --- LLM seam (tech spec §10) ---
    # Empty API key => the LLM-backed routes answer 503; everything else works.
    anthropic_api_key: str = ""
    llm_provider: str = "claude"
    llm_model: str = "claude-haiku-4-5-20251001"
    llm_daily_token_cap: int = 50_000

    # --- WHOOP OAuth2 / v2 API ---
    whoop_client_id: str = ""
    whoop_client_secret: str = ""
    whoop_redirect_uri: str = "http://localhost:8000/auth/whoop/callback"
    whoop_authorize_url: str = "https://api.prod.whoop.com/oauth/oauth2/auth"
    whoop_token_url: str = "https://api.prod.whoop.com/oauth/oauth2/token"
    whoop_api_base: str = "https://api.prod.whoop.com/developer/v2"
    whoop_scopes: str = (
        "read:recovery read:cycles read:sleep read:workout "
        "read:profile read:body_measurement offline"
    )

    # --- Mill Sense (indoor air quality) ---
    # Mill's cloud uses the Mill app account credentials (no OAuth / API keys).
    mill_username: str = ""
    mill_password: str = ""
    mill_api_base: str = "https://api.millnorwaycloud.com"

    # Optional in-app poller (off by default). Mill only serves the latest
    # reading, so polling on an interval is how a time series is built.
    mill_poll_enabled: bool = False
    mill_poll_interval_seconds: int = 300  # 5 min
    # Restrict polling to a nightly window (local server time, wraps midnight).
    # Leave both unset to poll around the clock. E.g. 22 and 8 -> 22:00–08:00.
    mill_poll_start_hour: int | None = None
    mill_poll_end_hour: int | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
