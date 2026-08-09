"""Canonical, source-agnostic health data model.

Designed as the *union* of what WHOOP's v2 API and other sources provide, so
additional adapters (HealthKit, goose BLE/raw, Oura, Garmin) map into the same
tables. Every ingested record carries provenance columns via ``SourceRecord``
and is de-duplicated on ``(source, source_external_id)``. The original source
payload is kept verbatim in ``raw`` so nothing is lost if a mapping is
incomplete and so records can be re-mapped later.
"""

from __future__ import annotations

from datetime import UTC, datetime
from datetime import date as dt_date

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


# --------------------------------------------------------------------------
# Connections & sync bookkeeping
# --------------------------------------------------------------------------
class WhoopConnection(Base):
    """Stored OAuth tokens for a WHOOP user (single-user dev: expect one row)."""

    __tablename__ = "whoop_connection"

    id: Mapped[int] = mapped_column(primary_key=True)
    whoop_user_id: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    access_token: Mapped[str] = mapped_column(String)
    refresh_token: Mapped[str | None] = mapped_column(String, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scope: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class MillConnection(Base):
    """Cached Mill cloud tokens (single-user dev: expect one row).

    Mill authenticates with the account's username/password (held in env), not
    OAuth; this table just caches the short-lived ``idToken`` and its
    ``refreshToken`` so we don't sign in on every poll.
    """

    __tablename__ = "mill_connection"

    id: Mapped[int] = mapped_column(primary_key=True)
    mill_user_id: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    access_token: Mapped[str] = mapped_column(String)  # Mill "idToken"
    refresh_token: Mapped[str | None] = mapped_column(String, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class SyncCursor(Base):
    """Per-source, per-resource incremental sync watermark."""

    __tablename__ = "sync_cursor"
    __table_args__ = (UniqueConstraint("source", "resource", name="uq_cursor_source_resource"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String)
    resource: Mapped[str] = mapped_column(String)  # recovery|sleep|workout|cycle
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


# --------------------------------------------------------------------------
# Provenance mixin for all ingested health records
# --------------------------------------------------------------------------
class SourceRecord:
    source: Mapped[str] = mapped_column(String, index=True)  # whoop_api|healthkit|...
    source_external_id: Mapped[str] = mapped_column(String, index=True)
    recorded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    score_state: Mapped[str | None] = mapped_column(String, nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    raw: Mapped[dict | None] = mapped_column(JSON, nullable=True)


# --------------------------------------------------------------------------
# Canonical health tables
# --------------------------------------------------------------------------
class RecoveryDaily(SourceRecord, Base):
    __tablename__ = "recovery_daily"
    __table_args__ = (
        UniqueConstraint("source", "source_external_id", name="uq_recovery_source_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    cycle_id: Mapped[str | None] = mapped_column(String, nullable=True)
    sleep_id: Mapped[str | None] = mapped_column(String, nullable=True)
    recovery_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    resting_hr_bpm: Mapped[float | None] = mapped_column(Float, nullable=True)
    hrv_rmssd_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    spo2_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    skin_temp_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    user_calibrating: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


class SleepSession(SourceRecord, Base):
    __tablename__ = "sleep_session"
    __table_args__ = (UniqueConstraint("source", "source_external_id", name="uq_sleep_source_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    timezone_offset: Mapped[str | None] = mapped_column(String, nullable=True)
    nap: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    sleep_performance_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    sleep_consistency_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    sleep_efficiency_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    respiratory_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_in_bed_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_awake_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_light_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_slow_wave_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)  # deep
    total_rem_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_no_data_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sleep_cycle_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    disturbance_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: How much of the night's sleep need came from accumulated debt (WHOOP
    #: ``sleep_needed.need_from_sleep_debt_milli``). Kept canonical rather than read out of
    #: ``raw`` downstream, so the derived layer never parses a source payload shape.
    sleep_debt_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    stages: Mapped[list[SleepStage]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class SleepStage(Base):
    """Per-stage durations for a sleep session (awake/light/slow_wave/rem/...)."""

    __tablename__ = "sleep_stage"

    id: Mapped[int] = mapped_column(primary_key=True)
    sleep_session_id: Mapped[int] = mapped_column(
        ForeignKey("sleep_session.id", ondelete="CASCADE"), index=True
    )
    stage_kind: Mapped[str] = mapped_column(String)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    session: Mapped[SleepSession] = relationship(back_populates="stages")


class Workout(SourceRecord, Base):
    __tablename__ = "workout"
    __table_args__ = (
        UniqueConstraint("source", "source_external_id", name="uq_workout_source_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    timezone_offset: Mapped[str | None] = mapped_column(String, nullable=True)
    sport_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sport_name: Mapped[str | None] = mapped_column(String, nullable=True)
    strain: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_hr_bpm: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_hr_bpm: Mapped[float | None] = mapped_column(Float, nullable=True)
    kilojoule: Mapped[float | None] = mapped_column(Float, nullable=True)
    distance_meter: Mapped[float | None] = mapped_column(Float, nullable=True)
    altitude_gain_meter: Mapped[float | None] = mapped_column(Float, nullable=True)
    altitude_change_meter: Mapped[float | None] = mapped_column(Float, nullable=True)
    zone_durations: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class CycleDay(SourceRecord, Base):
    """A WHOOP physiological cycle (~a day): daily strain & energy."""

    __tablename__ = "cycle_day"
    __table_args__ = (UniqueConstraint("source", "source_external_id", name="uq_cycle_source_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    timezone_offset: Mapped[str | None] = mapped_column(String, nullable=True)
    strain: Mapped[float | None] = mapped_column(Float, nullable=True)
    kilojoule: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_hr_bpm: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_hr_bpm: Mapped[float | None] = mapped_column(Float, nullable=True)


class Profile(SourceRecord, Base):
    __tablename__ = "profile"
    __table_args__ = (
        UniqueConstraint("source", "source_external_id", name="uq_profile_source_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str | None] = mapped_column(String, nullable=True)
    first_name: Mapped[str | None] = mapped_column(String, nullable=True)
    last_name: Mapped[str | None] = mapped_column(String, nullable=True)


class BodyMeasurement(SourceRecord, Base):
    __tablename__ = "body_measurement"
    __table_args__ = (UniqueConstraint("source", "source_external_id", name="uq_body_source_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    height_meter: Mapped[float | None] = mapped_column(Float, nullable=True)
    weight_kilogram: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_heart_rate: Mapped[int | None] = mapped_column(Integer, nullable=True)


class AirQualityReading(SourceRecord, Base):
    """A point-in-time indoor air-quality / environment sample.

    First populated by the Mill Sense sensor (``mill_sense`` source). The Mill
    cloud exposes only the *latest* snapshot per device, so a time series is
    built by polling on a schedule: each poll upserts one reading keyed on
    ``(source, device_id + poll-minute)``, which makes re-runs idempotent while
    letting distinct minutes accumulate. ``recorded_at`` is the poll time (the
    API exposes no per-reading timestamp). Units follow the Mill app; verify
    against live data on the first sync. Full payload kept in ``raw``.
    """

    __tablename__ = "air_quality_reading"
    __table_args__ = (
        UniqueConstraint("source", "source_external_id", name="uq_air_quality_source_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    device_name: Mapped[str | None] = mapped_column(String, nullable=True)
    temp_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    humidity_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    tvoc_ppb: Mapped[float | None] = mapped_column(Float, nullable=True)
    eco2_ppm: Mapped[float | None] = mapped_column(Float, nullable=True)
    pm1: Mapped[float | None] = mapped_column(Float, nullable=True)
    pm2_5: Mapped[float | None] = mapped_column(Float, nullable=True)
    pm10: Mapped[float | None] = mapped_column(Float, nullable=True)
    battery_pct: Mapped[float | None] = mapped_column(Float, nullable=True)


class VitalsTimeseries(Base):
    """High-resolution samples (e.g. WHOOP sleep /stream, future BLE raw).

    Not populated by the v1 backfill; the table exists so the stream endpoint
    and a future goose BLE adapter have a home.
    """

    __tablename__ = "vitals_timeseries"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String, index=True)
    source_external_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    metric: Mapped[str] = mapped_column(String, index=True)  # hr|skin_temp|...
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    value: Mapped[float] = mapped_column(Float)


# --------------------------------------------------------------------------
# Derived tables (written by app/derived/, never by a source)
#
# These are *computed* from the canonical tables above, so they are safe to drop and
# rebuild: `run_daily_derivation` reproduces them from source data. They still carry the
# `SourceRecord` provenance columns with `source="derived"`, so the one idempotent write
# path (`app.sync.orchestrator.upsert`) and the `(source, source_external_id)` unique
# constraint apply to them exactly as they do to ingested rows. See ADR-0009.
# --------------------------------------------------------------------------
class DailySummary(SourceRecord, Base):
    """One row per local date: everything known about a day, in one place.

    The shape the dashboard, the insight engine and the LLM brief all read, so nothing
    downstream has to re-derive "what happened on 2026-06-10" from six tables and a
    timezone rule. `source_external_id` is the ISO date, which is what makes recomputation
    idempotent.
    """

    __tablename__ = "daily_summary"
    __table_args__ = (
        UniqueConstraint("source", "source_external_id", name="uq_daily_summary_source_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[dt_date] = mapped_column(Date, unique=True, index=True)

    # --- recovery (that date's recovery, attributed per D1.3) ---
    recovery_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    hrv_rmssd_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    resting_hr_bpm: Mapped[float | None] = mapped_column(Float, nullable=True)
    spo2_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    skin_temp_c: Mapped[float | None] = mapped_column(Float, nullable=True)

    # --- the night's main sleep (naps excluded, D1.2) ---
    sleep_performance_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    sleep_efficiency_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    sleep_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sleep_debt_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rem_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    slow_wave_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    respiratory_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    disturbance_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # --- strain & training load (cycle + that date's workouts, D1.4) ---
    day_strain: Mapped[float | None] = mapped_column(Float, nullable=True)
    workout_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    workout_strain_sum: Mapped[float | None] = mapped_column(Float, nullable=True)
    kilojoule: Mapped[float | None] = mapped_column(Float, nullable=True)

    # --- indoor air during the night window (D1.5a) ---
    night_temp_c_avg: Mapped[float | None] = mapped_column(Float, nullable=True)
    night_eco2_ppm_avg: Mapped[float | None] = mapped_column(Float, nullable=True)
    night_eco2_ppm_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    night_tvoc_ppb_avg: Mapped[float | None] = mapped_column(Float, nullable=True)
    night_humidity_pct_avg: Mapped[float | None] = mapped_column(Float, nullable=True)

    # --- weather / daylight (filled by the open_meteo source in M3) ---
    weather_temp_min_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    weather_temp_max_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    daylight_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sunrise: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sunset: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # --- the daily check-in (filled by the manual source in M3) ---
    checkin_mood: Mapped[int | None] = mapped_column(Integer, nullable=True)
    checkin_energy: Mapped[int | None] = mapped_column(Integer, nullable=True)
    checkin_stress: Mapped[int | None] = mapped_column(Integer, nullable=True)
    checkin_soreness: Mapped[int | None] = mapped_column(Integer, nullable=True)
    alcohol_units: Mapped[float | None] = mapped_column(Float, nullable=True)
    caffeine_after_14: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    last_caffeine_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # --- the derived verdict ---
    readiness_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: The components and weights actually used, so the number can always be explained.
    readiness_components: Mapped[list | None] = mapped_column(JSON, nullable=True)
    #: Anomaly / warning dicts that fired for this date (see app/derived/flags.py).
    flags: Mapped[list | None] = mapped_column(JSON, nullable=True)


class Baseline(Base):
    """Trailing mean / SD per metric and window — "what is normal for me lately".

    Recomputed in place (no provenance mixin): a baseline is a cache of a calculation over
    `daily_summary`, not a record of something that happened. Windows always exclude the day
    being judged, so a value never influences the baseline it is compared against.
    """

    __tablename__ = "baseline"
    __table_args__ = (UniqueConstraint("metric", "window", name="uq_baseline_metric_window"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    metric: Mapped[str] = mapped_column(String, index=True)  # a daily_summary column name
    window: Mapped[int] = mapped_column(Integer)  # trailing days: 7 | 30 | 90
    mean: Mapped[float | None] = mapped_column(Float, nullable=True)
    sd: Mapped[float | None] = mapped_column(Float, nullable=True)
    n: Mapped[int] = mapped_column(Integer, default=0)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class InsightCard(SourceRecord, Base):
    """A finding worth showing the owner: an anomaly, a warning, a correlation.

    One row per *finding*, not per day — `source_external_id` is a deterministic key for the
    finding itself (e.g. ``"anomaly:hrv_drop"``), so re-running the engine updates the card's
    status and `last_confirmed` instead of accumulating a new copy every day. The statistics
    fields are filled by the correlation engine in M4; M2 only writes anomaly and
    illness-warning cards.
    """

    __tablename__ = "insight_card"
    __table_args__ = (
        UniqueConstraint("source", "source_external_id", name="uq_insight_card_source_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String, index=True)  # correlation|illness_warning|...
    title: Mapped[str] = mapped_column(String)
    body: Mapped[str] = mapped_column(String)
    metric_x: Mapped[str | None] = mapped_column(String, nullable=True)
    metric_y: Mapped[str | None] = mapped_column(String, nullable=True)
    effect_size: Mapped[float | None] = mapped_column(Float, nullable=True)
    n: Mapped[int | None] = mapped_column(Integer, nullable=True)
    p_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    lag_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_confirmed: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    status: Mapped[str] = mapped_column(String, default="active")  # active|expired|dismissed


# Tables exposed by the export consumer (excludes connection/cursor bookkeeping).
# Annotated explicitly: the entries have different base combinations (some mix in
# SourceRecord, some don't), so an inferred element type can collapse to `type[object]` —
# which makes the `__tablename__` / `__table__` access in app/export/exporter.py fail to
# type-check. Naming `type[Base]` keeps the mapped-class attributes visible.
EXPORT_MODELS: list[type[Base]] = [
    RecoveryDaily,
    SleepSession,
    SleepStage,
    Workout,
    CycleDay,
    Profile,
    BodyMeasurement,
    AirQualityReading,
    VitalsTimeseries,
]
