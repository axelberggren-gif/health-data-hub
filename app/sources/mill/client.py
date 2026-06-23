"""Thin Mill cloud client: bearer auth, rate-limit backoff, device discovery.

Walks houses -> independent devices + room devices and yields the raw device
payloads. The Sense sensor's readings live on each device's ``lastMetrics``;
sensors are distinguished from heaters/sockets by
``deviceType.parentType.name == "Sensors"``.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from datetime import date

import httpx

from ...config import get_settings

settings = get_settings()

_MAX_RETRIES = 6
_MAX_BACKOFF_SECONDS = 60

DEVICE_TYPE_SENSORS = "Sensors"


class MillAPIError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


class MillClient:
    """Authenticated Mill cloud client. Use as a context manager."""

    def __init__(self, access_token: str):
        self._client = httpx.Client(
            base_url=settings.mill_api_base,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=30,
        )

    def __enter__(self) -> MillClient:
        return self

    def __exit__(self, *exc) -> None:
        self._client.close()

    def _request(self, method: str, path: str, **kwargs):
        for _ in range(_MAX_RETRIES):
            resp = self._client.request(method, path, **kwargs)
            if resp.status_code == 429:
                reset = resp.headers.get("Retry-After", "5")
                try:
                    delay = min(max(int(reset), 1), _MAX_BACKOFF_SECONDS)
                except ValueError:
                    delay = 5
                time.sleep(delay)
                continue
            if resp.status_code >= 400:
                raise MillAPIError(
                    resp.status_code, f"{resp.status_code} {method} {path}: {resp.text[:300]}"
                )
            return resp.json()
        raise MillAPIError(429, f"rate limited repeatedly on {method} {path}")

    def _get(self, path: str, params: dict | None = None):
        return self._request("GET", path, params=params)

    def fetch_statistics(self, device_id: str, day: date, period: str = "hourly") -> dict:
        """POST the (energy-centric) statistics endpoint; see history.py for why."""
        return self._request(
            "POST",
            f"devices/{device_id}/statistics",
            json={"period": period, "year": day.year, "month": day.month, "day": day.day},
        )

    # ---- discovery --------------------------------------------------------
    def list_houses(self) -> list[dict]:
        data = self._get("houses") or {}
        return data.get("ownHouses", []) or []

    def _devices_in_house(self, house_id) -> Iterator[dict]:
        """Yield every device in a house (independent + per-room)."""
        independent = self._get(f"houses/{house_id}/devices/independent") or {}
        yield from independent.get("items", []) or []

        rooms = self._get(f"houses/{house_id}/devices") or []
        if isinstance(rooms, list):
            for room in rooms:
                if isinstance(room, dict):
                    yield from room.get("devices", []) or []

    def iter_sensor_devices(self) -> Iterator[dict]:
        """Yield raw device payloads for air-quality sensors across all houses."""
        for house in self.list_houses():
            house_id = house.get("id")
            if house_id is None:
                continue
            for device in self._devices_in_house(house_id):
                if not isinstance(device, dict):
                    continue
                parent = (device.get("deviceType") or {}).get("parentType") or {}
                if parent.get("name") == DEVICE_TYPE_SENSORS:
                    yield device
