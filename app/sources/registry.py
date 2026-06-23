"""Registry of available data sources. Add new adapters here."""

from __future__ import annotations

from sqlalchemy.orm import Session

from .base import HealthDataSource
from .mill.source import MillSenseSource
from .whoop.source import WhoopApiSource

_SOURCES: dict[str, type[HealthDataSource]] = {
    WhoopApiSource.name: WhoopApiSource,
    MillSenseSource.name: MillSenseSource,
    # Future: HealthKitSource, WhoopBleSource, OuraSource, GarminSource, ...
}


def get_source(name: str, db: Session) -> HealthDataSource:
    if name not in _SOURCES:
        raise KeyError(f"unknown source '{name}'. available: {sorted(_SOURCES)}")
    # Concrete sources take `db` in __init__; the ABC type doesn't declare it.
    return _SOURCES[name](db)  # type: ignore[call-arg]


def available_sources() -> list[str]:
    return sorted(_SOURCES)
