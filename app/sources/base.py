"""The source-agnostic ingestion seam.

Every data source (WHOOP API now; HealthKit, goose BLE, Oura, Garmin later)
implements ``HealthDataSource`` and maps its native payloads into the canonical
model. New sources plug in without touching the store, sync, or export layers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class SyncResult:
    source: str
    counts: dict[str, int] = field(default_factory=dict)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    notes: list[str] = field(default_factory=list)

    def add(self, resource: str, n: int) -> None:
        self.counts[resource] = self.counts.get(resource, 0) + n


class HealthDataSource(ABC):
    """Contract for a pluggable health data source."""

    #: stable identifier stored in ``SourceRecord.source``
    name: str = "base"

    @abstractmethod
    def capabilities(self) -> set[str]:
        """Resource families this source can provide (recovery/sleep/...)."""

    def authorize_url(self, state: str) -> str:
        """Return an OAuth authorize URL, if the source uses OAuth."""
        raise NotImplementedError(f"{self.name} does not use OAuth")

    @abstractmethod
    def backfill(self, start: datetime, end: datetime | None = None) -> SyncResult:
        """Pull a historical window and upsert into the canonical store."""

    @abstractmethod
    def sync_incremental(self) -> SyncResult:
        """Pull everything new since the stored cursor."""

    def handle_webhook(self, payload: dict) -> SyncResult:
        """Ingest a single push event (sources that support webhooks)."""
        raise NotImplementedError(f"{self.name} does not support webhooks")
