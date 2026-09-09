"""HTTP access to Open-Meteo.

Open-Meteo serves recent and forecast days from one host and deep history from another,
but both speak the same `daily=` query and return the same shape — so one function covers
both and the caller picks the endpoint.
"""

from __future__ import annotations

from datetime import date

import httpx

#: The daily fields we ask for. Ordering is irrelevant to the API but keeps request logs
#: and test assertions stable.
DAILY_FIELDS = (
    "temperature_2m_min",
    "temperature_2m_max",
    "precipitation_sum",
    "sunrise",
    "sunset",
    "daylight_duration",
)

TIMEOUT_SECONDS = 20.0


def fetch_daily(
    url: str,
    *,
    latitude: float,
    longitude: float,
    timezone: str,
    start: date,
    end: date,
) -> dict:
    """One day-range request. Raises `httpx.HTTPError` on a transport or status failure.

    `timezone` is passed through so Open-Meteo buckets days — and renders sunrise/sunset —
    in the owner's local calendar rather than UTC, which is the same day definition the
    derived layer uses (D1).
    """
    params: dict[str, str | float] = {
        "latitude": latitude,
        "longitude": longitude,
        "timezone": timezone,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "daily": ",".join(DAILY_FIELDS),
    }
    with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
        response = client.get(url, params=params)
        response.raise_for_status()
        return response.json()
