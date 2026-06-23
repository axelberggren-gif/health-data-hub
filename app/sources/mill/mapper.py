"""Map Mill device payloads into canonical ``AirQualityReading`` field dicts.

Field names follow the Mill cloud schema as read by the reference integration
(``lastMetrics``: ``temperature``, ``humidity``, ``tvoc``, ``eco2``,
``batteryPercentage``, ``massPm_10/25/100``). All access is defensive and the
full payload is preserved in ``raw`` so unmapped fields are never lost. Verify
units/keys against live data on the first sync.
"""

from __future__ import annotations

from datetime import datetime

SOURCE = "mill_sense"


def device_id_of(device: dict) -> str | None:
    """Stable per-device identifier, tolerant of key naming."""
    for key in ("deviceId", "id", "macAddress", "deviceName"):
        value = device.get(key)
        if value:
            return str(value)
    return None


def device_name_of(device: dict) -> str | None:
    for key in ("customName", "deviceName", "name"):
        value = device.get(key)
        if value:
            return str(value)
    return None


def map_sensor(device: dict, recorded_at: datetime) -> tuple[str | None, dict]:
    """Return ``(device_id, values)`` for one sensor snapshot."""
    metrics = device.get("lastMetrics") or {}
    device_id = device_id_of(device)
    values = {
        "device_id": device_id,
        "device_name": device_name_of(device),
        "recorded_at": recorded_at,
        # temperature key varies by firmware; prefer the documented one.
        "temp_c": metrics.get("temperature", metrics.get("temperatureAmbient")),
        "humidity_pct": metrics.get("humidity"),
        "tvoc_ppb": metrics.get("tvoc"),
        "eco2_ppm": metrics.get("eco2"),
        "pm1": metrics.get("massPm_10"),
        "pm2_5": metrics.get("massPm_25"),
        "pm10": metrics.get("massPm_100"),
        "battery_pct": metrics.get("batteryPercentage"),
        "raw": device,
    }
    return device_id, values
