"""Thin WHOOP v2 API client: bearer auth, pagination, rate-limit backoff."""

from __future__ import annotations

import time
from collections.abc import Iterator

import httpx

from ...config import get_settings

settings = get_settings()

_MAX_RETRIES = 6
_MAX_BACKOFF_SECONDS = 60


class WhoopAPIError(Exception):
    pass


class WhoopClient:
    """Authenticated client. Use as a context manager."""

    def __init__(self, access_token: str):
        self._client = httpx.Client(
            base_url=settings.whoop_api_base,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=30,
        )

    def __enter__(self) -> WhoopClient:
        return self

    def __exit__(self, *exc) -> None:
        self._client.close()

    def _get(self, path: str, params: dict | None = None) -> dict:
        for _ in range(_MAX_RETRIES):
            resp = self._client.get(path, params=params)
            if resp.status_code == 429:
                # Honor X-RateLimit-Reset (seconds) when present.
                reset = resp.headers.get("X-RateLimit-Reset", "5")
                try:
                    delay = min(max(int(reset), 1), _MAX_BACKOFF_SECONDS)
                except ValueError:
                    delay = 5
                time.sleep(delay)
                continue
            if resp.status_code >= 400:
                raise WhoopAPIError(f"{resp.status_code} GET {path}: {resp.text[:300]}")
            return resp.json()
        raise WhoopAPIError(f"rate limited repeatedly on GET {path}")

    def get_record(self, path: str) -> dict:
        """Fetch a single resource (e.g. /user/profile/basic)."""
        return self._get(path)

    def iter_collection(
        self,
        path: str,
        start: str | None = None,
        end: str | None = None,
        limit: int = 25,
    ) -> Iterator[dict]:
        """Yield every record across pages of a collection endpoint."""
        base: dict[str, object] = {"limit": limit}
        if start:
            base["start"] = start
        if end:
            base["end"] = end

        next_token: str | None = None
        while True:
            params = {"limit": limit, "nextToken": next_token} if next_token else base
            data = self._get(path, params=params)
            yield from data.get("records", [])
            next_token = data.get("next_token")
            if not next_token:
                break
