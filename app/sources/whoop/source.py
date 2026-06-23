"""WhoopApiSource — the v1 data source, built on the official WHOOP v2 API."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import (
    BodyMeasurement,
    CycleDay,
    Profile,
    RecoveryDaily,
    SleepSession,
    SleepStage,
    WhoopConnection,
    Workout,
)
from ...sync.orchestrator import get_cursor, set_cursor, upsert
from ..base import HealthDataSource, SyncResult
from . import mapper, oauth
from .client import WhoopClient

_TOKEN_SKEW = timedelta(seconds=60)


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _as_aware(dt: datetime | None) -> datetime | None:
    """Coerce a possibly-naive datetime (SQLite drops tzinfo) to aware UTC."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


class WhoopApiSource(HealthDataSource):
    name = "whoop_api"

    def __init__(self, db: Session):
        self.db = db

    def capabilities(self) -> set[str]:
        return {"recovery", "sleep", "workout", "cycle", "profile", "body"}

    def authorize_url(self, state: str) -> str:
        return oauth.build_authorize_url(state)

    # ---- token management -------------------------------------------------
    def _connection(self) -> WhoopConnection:
        conn = (
            self.db.execute(select(WhoopConnection).order_by(WhoopConnection.id.desc()))
            .scalars()
            .first()
        )
        if conn is None:
            raise RuntimeError("No WHOOP connection. Visit /auth/whoop/login first.")
        return conn

    def _fresh_access_token(self) -> str:
        conn = self._connection()
        expires_at = _as_aware(conn.expires_at)
        expired = expires_at is not None and expires_at <= datetime.now(UTC) + _TOKEN_SKEW
        if expired:
            if not conn.refresh_token:
                raise RuntimeError("Access token expired and no refresh token; re-authorize.")
            tokens = oauth.refresh_tokens(conn.refresh_token)
            conn.access_token = tokens["access_token"]
            if tokens.get("refresh_token"):
                conn.refresh_token = tokens["refresh_token"]
            if tokens.get("expires_in"):
                conn.expires_at = datetime.now(UTC) + timedelta(seconds=int(tokens["expires_in"]))
            if tokens.get("scope"):
                conn.scope = tokens["scope"]
            self.db.commit()
        return conn.access_token

    # ---- sync -------------------------------------------------------------
    def backfill(self, start: datetime, end: datetime | None = None) -> SyncResult:
        return self._sync(start, end)

    def sync_incremental(self) -> SyncResult:
        earliest: datetime | None = None
        for resource in ("recovery", "sleep", "workout", "cycle"):
            cursor = get_cursor(self.db, self.name, resource)
            if cursor and (earliest is None or cursor < earliest):
                earliest = cursor
        start = earliest or datetime.now(UTC) - timedelta(days=7)
        return self._sync(start, None)

    def _sync(self, start: datetime | None, end: datetime | None) -> SyncResult:
        result = SyncResult(source=self.name, started_at=datetime.now(UTC))
        token = self._fresh_access_token()
        start_iso = _iso(start) if start else None
        end_iso = _iso(end) if end else None
        now = datetime.now(UTC)

        with WhoopClient(token) as client:
            # Profile + body measurement (single records).
            try:
                profile = client.get_record("/user/profile/basic")
                ext, values = mapper.map_profile(profile)
                upsert(self.db, Profile, source=self.name, source_external_id=ext, values=values)
                result.add("profile", 1)

                body = client.get_record("/user/measurement/body")
                bext, bvalues = mapper.map_body(body, profile.get("user_id"))
                upsert(
                    self.db,
                    BodyMeasurement,
                    source=self.name,
                    source_external_id=bext,
                    values=bvalues,
                )
                result.add("body", 1)
            except Exception as exc:  # non-fatal; continue with time series
                result.notes.append(f"profile/body skipped: {exc}")

            # Cycles.
            count = 0
            for rec in client.iter_collection("/cycle", start_iso, end_iso):
                ext, values = mapper.map_cycle(rec)
                if ext:
                    upsert(
                        self.db, CycleDay, source=self.name, source_external_id=ext, values=values
                    )
                    count += 1
            result.add("cycle", count)
            set_cursor(self.db, self.name, "cycle", now)

            # Recovery.
            count = 0
            for rec in client.iter_collection("/recovery", start_iso, end_iso):
                ext, values = mapper.map_recovery(rec)
                if ext:
                    upsert(
                        self.db,
                        RecoveryDaily,
                        source=self.name,
                        source_external_id=ext,
                        values=values,
                    )
                    count += 1
            result.add("recovery", count)
            set_cursor(self.db, self.name, "recovery", now)

            # Sleep (+ per-stage durations).
            count = 0
            for rec in client.iter_collection("/activity/sleep", start_iso, end_iso):
                ext, values, stages = mapper.map_sleep(rec)
                if not ext:
                    continue
                obj, _ = upsert(
                    self.db, SleepSession, source=self.name, source_external_id=ext, values=values
                )
                self.db.flush()  # assign id before attaching children
                obj.stages = [
                    SleepStage(stage_kind=kind, duration_ms=duration) for kind, duration in stages
                ]
                count += 1
            result.add("sleep", count)
            set_cursor(self.db, self.name, "sleep", now)

            # Workouts.
            count = 0
            for rec in client.iter_collection("/activity/workout", start_iso, end_iso):
                ext, values = mapper.map_workout(rec)
                if ext:
                    upsert(
                        self.db, Workout, source=self.name, source_external_id=ext, values=values
                    )
                    count += 1
            result.add("workout", count)
            set_cursor(self.db, self.name, "workout", now)

        self.db.commit()
        result.finished_at = datetime.now(UTC)
        return result
