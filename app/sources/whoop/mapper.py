"""Map WHOOP v2 API payloads into canonical-model field dicts.

WHOOP wraps metrics in a ``score`` object alongside a top-level ``score_state``
(SCORED / PENDING_SCORE / UNSCORABLE). All access is defensive (``.get``) and
the full payload is preserved in ``raw`` so unmapped fields are never lost.

NOTE: field names follow WHOOP's documented v2 schema. Verify against the live
API / OpenAPI spec during the first real sync — especially ``hrv_rmssd_milli``
units and v2 id types (UUID vs int).
"""

from __future__ import annotations

from datetime import datetime

SOURCE = "whoop_api"


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _str(value) -> str | None:
    return str(value) if value is not None else None


def map_recovery(rec: dict) -> tuple[str, dict]:
    """Recovery has no own id; it is keyed by its cycle."""
    score = rec.get("score") or {}
    external_id = _str(rec.get("cycle_id")) or ""
    values = {
        "cycle_id": _str(rec.get("cycle_id")),
        "sleep_id": _str(rec.get("sleep_id")),
        "recorded_at": _dt(rec.get("created_at")),
        "score_state": rec.get("score_state"),
        "recovery_score": score.get("recovery_score"),
        "resting_hr_bpm": score.get("resting_heart_rate"),
        "hrv_rmssd_ms": score.get("hrv_rmssd_milli"),
        "spo2_pct": score.get("spo2_percentage"),
        "skin_temp_c": score.get("skin_temp_celsius"),
        "user_calibrating": score.get("user_calibrating"),
        "raw": rec,
    }
    return external_id, values


_STAGE_KEYS = [
    ("awake", "total_awake_time_milli"),
    ("light", "total_light_sleep_time_milli"),
    ("slow_wave", "total_slow_wave_sleep_time_milli"),  # "deep"
    ("rem", "total_rem_sleep_time_milli"),
    ("no_data", "total_no_data_time_milli"),
    ("in_bed", "total_in_bed_time_milli"),
]


def map_sleep(rec: dict) -> tuple[str, dict, list[tuple[str, int]]]:
    score = rec.get("score") or {}
    summary = score.get("stage_summary") or {}
    needed = score.get("sleep_needed") or {}
    external_id = _str(rec.get("id")) or ""
    values = {
        "start": _dt(rec.get("start")),
        "end": _dt(rec.get("end")),
        "timezone_offset": rec.get("timezone_offset"),
        "nap": rec.get("nap"),
        "recorded_at": _dt(rec.get("start")),
        "score_state": rec.get("score_state"),
        "sleep_performance_pct": score.get("sleep_performance_percentage"),
        "sleep_consistency_pct": score.get("sleep_consistency_percentage"),
        "sleep_efficiency_pct": score.get("sleep_efficiency_percentage"),
        "respiratory_rate": score.get("respiratory_rate"),
        "total_in_bed_ms": summary.get("total_in_bed_time_milli"),
        "total_awake_ms": summary.get("total_awake_time_milli"),
        "total_light_ms": summary.get("total_light_sleep_time_milli"),
        "total_slow_wave_ms": summary.get("total_slow_wave_sleep_time_milli"),
        "total_rem_ms": summary.get("total_rem_sleep_time_milli"),
        "total_no_data_ms": summary.get("total_no_data_time_milli"),
        "sleep_cycle_count": summary.get("sleep_cycle_count"),
        "disturbance_count": summary.get("disturbance_count"),
        "sleep_debt_ms": needed.get("need_from_sleep_debt_milli"),
        "raw": rec,
    }
    stages = [(kind, summary[key]) for kind, key in _STAGE_KEYS if summary.get(key) is not None]
    return external_id, values, stages


def map_workout(rec: dict) -> tuple[str, dict]:
    score = rec.get("score") or {}
    external_id = _str(rec.get("id")) or ""
    values = {
        "start": _dt(rec.get("start")),
        "end": _dt(rec.get("end")),
        "timezone_offset": rec.get("timezone_offset"),
        "sport_id": rec.get("sport_id"),
        "sport_name": rec.get("sport_name"),
        "recorded_at": _dt(rec.get("start")),
        "score_state": rec.get("score_state"),
        "strain": score.get("strain"),
        "avg_hr_bpm": score.get("average_heart_rate"),
        "max_hr_bpm": score.get("max_heart_rate"),
        "kilojoule": score.get("kilojoule"),
        "distance_meter": score.get("distance_meter"),
        "altitude_gain_meter": score.get("altitude_gain_meter"),
        "altitude_change_meter": score.get("altitude_change_meter"),
        "zone_durations": score.get("zone_duration"),
        "raw": rec,
    }
    return external_id, values


def map_cycle(rec: dict) -> tuple[str, dict]:
    score = rec.get("score") or {}
    external_id = _str(rec.get("id")) or ""
    values = {
        "start": _dt(rec.get("start")),
        "end": _dt(rec.get("end")),
        "timezone_offset": rec.get("timezone_offset"),
        "recorded_at": _dt(rec.get("start")),
        "score_state": rec.get("score_state"),
        "strain": score.get("strain"),
        "kilojoule": score.get("kilojoule"),
        "avg_hr_bpm": score.get("average_heart_rate"),
        "max_hr_bpm": score.get("max_heart_rate"),
        "raw": rec,
    }
    return external_id, values


def map_profile(rec: dict) -> tuple[str, dict]:
    external_id = _str(rec.get("user_id")) or ""
    values = {
        "email": rec.get("email"),
        "first_name": rec.get("first_name"),
        "last_name": rec.get("last_name"),
        "raw": rec,
    }
    return external_id, values


def map_body(rec: dict, user_id) -> tuple[str, dict]:
    external_id = _str(user_id) or ""
    values = {
        "height_meter": rec.get("height_meter"),
        "weight_kilogram": rec.get("weight_kilogram"),
        "max_heart_rate": rec.get("max_heart_rate"),
        "raw": rec,
    }
    return external_id, values
