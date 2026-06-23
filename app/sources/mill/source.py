"""MillSenseSource — indoor air quality from the Mill Sense via the Mill cloud.

Unlike WHOOP, the Mill cloud exposes only the *current* reading per device, so
there is no historical collection to page through. ``sync_incremental`` polls
the latest snapshot for every Sense sensor on the account and upserts one
``AirQualityReading`` per device, keyed to the poll minute. Run it on a
schedule (e.g. every few minutes overnight) and the readings accumulate into a
time series you can align against sleep sessions.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...config import get_settings
from ...models import AirQualityReading, MillConnection
from ...sync.orchestrator import set_cursor, upsert
from ..base import HealthDataSource, SyncResult
from . import auth, history, mapper
from .client import MillAPIError, MillClient


def _minute_key(dt: datetime) -> str:
    """UTC minute bucket used as the per-reading external id."""
    return dt.astimezone(UTC).replace(second=0, microsecond=0).isoformat().replace("+00:00", "Z")


def _as_aware(dt: datetime | None) -> datetime | None:
    """Coerce a possibly-naive datetime (SQLite drops tzinfo) to aware UTC."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


_TOKEN_SKEW = timedelta(seconds=60)


class MillSenseSource(HealthDataSource):
    name = "mill_sense"

    def __init__(self, db: Session):
        self.db = db

    def capabilities(self) -> set[str]:
        return {"air_quality"}

    # ---- credentials & token management -----------------------------------
    def _credentials(self) -> tuple[str, str]:
        settings = get_settings()
        if not settings.mill_username or not settings.mill_password:
            raise RuntimeError(
                "Mill credentials not configured; set MILL_USERNAME and "
                "MILL_PASSWORD in .env (your Mill app login)."
            )
        return settings.mill_username, settings.mill_password

    def _connection(self) -> MillConnection | None:
        return (
            self.db.execute(select(MillConnection).order_by(MillConnection.id.desc()))
            .scalars()
            .first()
        )

    def _persist(self, conn: MillConnection, tokens: dict) -> None:
        conn.access_token = tokens["access_token"]
        if tokens.get("refresh_token"):
            conn.refresh_token = tokens["refresh_token"]
        conn.expires_at = tokens.get("expires_at")
        self.db.commit()

    def _sign_in_fresh(self, username: str, password: str) -> str:
        tokens = auth.sign_in(username, password)
        conn = self._connection()
        if conn is None:
            conn = MillConnection(access_token=tokens["access_token"])
            self.db.add(conn)
        self._persist(conn, tokens)
        return conn.access_token

    def _fresh_access_token(self, username: str, password: str) -> str:
        conn = self._connection()
        if conn is None:
            return self._sign_in_fresh(username, password)
        expires_at = _as_aware(conn.expires_at)
        expired = expires_at is not None and expires_at <= datetime.now(UTC) + _TOKEN_SKEW
        if not expired:
            return conn.access_token
        if conn.refresh_token:
            try:
                self._persist(conn, auth.refresh_tokens(conn.refresh_token))
                return conn.access_token
            except httpx.HTTPError:
                pass  # refresh failed; fall back to a full sign-in
        return self._sign_in_fresh(username, password)

    # ---- sync -------------------------------------------------------------
    def sync_incremental(self) -> SyncResult:
        return self._poll()

    def backfill(self, start: datetime, end: datetime | None = None) -> SyncResult:
        """Pull historical air quality from the Mill cloud statistics endpoint.

        The statistics endpoint returns per-metric hourly history (~3 weeks
        retention, confirmed against a GL-Sense); ``history.parse_statistics``
        turns it into one reading per hourly bucket. Falls back to the generic
        extractor for unknown shapes, and notes if nothing comes back so you can
        inspect ``GET /mill/diagnose``.
        """
        result = SyncResult(source=self.name, started_at=datetime.now(UTC))
        username, password = self._credentials()
        token = self._fresh_access_token(username, password)
        start_d = start.astimezone(UTC).date()
        end_d = (end or datetime.now(UTC)).astimezone(UTC).date()
        try:
            self._backfill_collect(token, result, start_d, end_d)
        except MillAPIError as exc:
            if exc.status_code != 401:
                raise
            result.counts.clear()
            result.notes.append("re-authenticated after 401")
            token = self._sign_in_fresh(username, password)
            self._backfill_collect(token, result, start_d, end_d)
        self.db.commit()
        result.finished_at = datetime.now(UTC)
        return result

    def _backfill_collect(self, token, result, start_d, end_d) -> None:
        samples = 0
        sensors = 0
        with MillClient(token) as client:
            for device in client.iter_sensor_devices():
                sensors += 1
                device_id = mapper.device_id_of(device)
                if not device_id:
                    continue
                device_name = mapper.device_name_of(device)
                for day in history.daterange(start_d, end_d):
                    try:
                        raw = client.fetch_statistics(device_id, day, period="hourly")
                    except MillAPIError as exc:
                        if exc.status_code == 401:
                            raise
                        result.notes.append(f"statistics {day} failed: {exc}")
                        continue
                    day_samples = list(history.parse_statistics(raw)) or list(
                        history.iter_history_samples(raw)
                    )
                    for ts, metrics in day_samples:
                        values = {
                            "device_id": device_id,
                            "device_name": device_name,
                            "recorded_at": ts,
                            "raw": {"statistics_day": day.isoformat(), "metrics": metrics},
                            **metrics,
                        }
                        upsert(
                            self.db,
                            AirQualityReading,
                            source=self.name,
                            source_external_id=f"{device_id}:{_minute_key(ts)}",
                            values=values,
                        )
                        samples += 1
        result.add("air_quality", samples)
        if sensors == 0:
            result.notes.append("no Mill Sense (Sensors) devices found on this account")
        elif samples == 0:
            result.notes.append(
                "No historical air-quality samples came back from /statistics for "
                "your sensor(s) — Mill likely serves the app's history graph from a "
                "different endpoint. Run GET /mill/diagnose to capture the real "
                "payload so the backfill mapping can be finalized."
            )

    def diagnose(self) -> dict:
        """Dump raw sensor + statistics payloads to reveal the history shape.

        Dev tool: shows each sensor's ``lastMetrics`` and the raw ``/statistics``
        response (hourly + daily, today) so we can see exactly what Mill returns
        and finalize the historical mapping in ``history.py``.
        """
        username, password = self._credentials()
        token = self._fresh_access_token(username, password)
        today = datetime.now(UTC).date()
        out: dict = {"sensors": []}
        with MillClient(token) as client:
            for device in client.iter_sensor_devices():
                entry: dict = {
                    "device_id": mapper.device_id_of(device),
                    "device_name": mapper.device_name_of(device),
                    "lastMetrics": device.get("lastMetrics"),
                    "statistics": {},
                }
                device_id = entry["device_id"]
                if device_id:
                    for period in ("hourly", "daily"):
                        try:
                            entry["statistics"][period] = client.fetch_statistics(
                                device_id, today, period=period
                            )
                        except MillAPIError as exc:
                            entry["statistics"][period] = {
                                "error": str(exc),
                                "status": exc.status_code,
                            }
                out["sensors"].append(entry)
        return out

    def _poll(self) -> SyncResult:
        result = SyncResult(source=self.name, started_at=datetime.now(UTC))
        username, password = self._credentials()
        token = self._fresh_access_token(username, password)
        try:
            self._collect(token, result)
        except MillAPIError as exc:
            if exc.status_code != 401:
                raise
            # Cached token rejected — sign in fresh once and retry.
            result.counts.clear()
            result.notes.append("re-authenticated after 401")
            token = self._sign_in_fresh(username, password)
            self._collect(token, result)
        self.db.commit()
        result.finished_at = datetime.now(UTC)
        return result

    def _collect(self, token: str, result: SyncResult) -> None:
        now = datetime.now(UTC)
        # Bucket the poll to the minute so re-runs within a minute are idempotent
        # while distinct polls accumulate as a time series.
        bucket = _minute_key(now)
        count = 0
        seen = 0
        with MillClient(token) as client:
            for device in client.iter_sensor_devices():
                seen += 1
                device_id, values = mapper.map_sensor(device, now)
                if not device_id:
                    result.notes.append("skipped a sensor with no resolvable device id")
                    continue
                upsert(
                    self.db,
                    AirQualityReading,
                    source=self.name,
                    source_external_id=f"{device_id}:{bucket}",
                    values=values,
                )
                count += 1
        result.add("air_quality", count)
        if seen == 0:
            result.notes.append("no Mill Sense (Sensors) devices found on this account")
        set_cursor(self.db, self.name, "air_quality", now)
