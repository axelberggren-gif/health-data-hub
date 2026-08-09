"""Anomaly flags and the illness early-warning (tech spec §8).

Rule-based on purpose: the owner has to be able to read why a warning appeared, and a rule
with a printed threshold can be argued with. Each firing rule appends a dict to
`daily_summary.flags` and upserts an `insight_card`, so the same finding is one row that
gains a `last_confirmed` rather than a new row every day.

Two design points worth keeping:

* **Comparisons use a z rounded to 3 decimals.** The thresholds are exact numbers (−1.5, not
  "about −1.5"), and rounding first means a value that is mathematically on the line fires
  deterministically instead of depending on floating-point drift.
* **The illness warning is a conjunction.** One signal is a bad night. Two at once is a
  pattern worth mentioning — and the wording stays non-diagnostic, because this is a set of
  thresholds over consumer sensors, not a medical opinion.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import DailySummary, InsightCard, utcnow
from ..sync.orchestrator import upsert
from . import DERIVED_SOURCE
from .baselines import load_baselines, z_score

#: Thresholds, all in z-score units unless the name says otherwise.
Z_HRV_DROP = -1.5
Z_RHR_ELEVATED = 1.5
Z_RESP_RATE_UP = 1.5
SKIN_TEMP_RISE_C = 0.5
SLEEP_DEBT_RATIO = 0.9
BAD_AIR_ECO2_PPM = 1000.0
BAD_AIR_NIGHTS = 3

#: Decimals kept when comparing and reporting a z-score (see the module docstring).
Z_PRECISION = 3

#: Firing any two of these on one day raises the illness early-warning.
ILLNESS_SIGNALS = ("hrv_drop", "rhr_elevated", "resp_rate_up", "skin_temp_up")
ILLNESS_MIN_SIGNALS = 2

#: The window a z-score is measured against.
Z_WINDOW = 30

_STATUS_ACTIVE = "active"
_STATUS_EXPIRED = "expired"
_STATUS_DISMISSED = "dismissed"

#: Card kinds this module owns. The correlation engine (M4) manages its own.
_RULE_CARD_KINDS = ("anomaly", "illness_warning")

_TITLES = {
    "hrv_drop": "HRV below your baseline",
    "rhr_elevated": "Resting heart rate above your baseline",
    "resp_rate_up": "Respiratory rate above your baseline",
    "skin_temp_up": "Skin temperature above your baseline",
    "sleep_debt": "Sleep is trending short",
    "bad_air_streak": "Bedroom air has been stale",
    "illness_warning": "Your body is under strain",
}


def apply_flags(db: Session, day: date) -> list[dict[str, Any]]:
    """Evaluate every rule for `day`, store the flags on its summary, and sync the cards.

    Returns the flags that fired. The caller commits.
    """
    summary = db.execute(select(DailySummary).where(DailySummary.date == day)).scalar_one_or_none()
    if summary is None:
        return []

    baselines = load_baselines(db)
    flags = [
        flag
        for flag in (
            _z_flag(
                summary,
                baselines,
                kind="hrv_drop",
                metric="hrv_rmssd_ms",
                threshold=Z_HRV_DROP,
            ),
            _z_flag(
                summary,
                baselines,
                kind="rhr_elevated",
                metric="resting_hr_bpm",
                threshold=Z_RHR_ELEVATED,
            ),
            _z_flag(
                summary,
                baselines,
                kind="resp_rate_up",
                metric="respiratory_rate",
                threshold=Z_RESP_RATE_UP,
            ),
            _skin_temp_flag(summary, baselines),
            _sleep_debt_flag(baselines),
            _bad_air_streak_flag(db, day),
        )
        if flag is not None
    ]

    warning = _illness_warning(flags)
    if warning is not None:
        flags.append(warning)

    summary.flags = flags
    _sync_cards(db, flags)
    db.flush()  # autoflush is off on SessionLocal; make the cards queryable before commit
    return flags


# --------------------------------------------------------------------------
# Individual rules
# --------------------------------------------------------------------------
def _z_flag(
    summary: DailySummary,
    baselines: dict[tuple[str, int], Any],
    *,
    kind: str,
    metric: str,
    threshold: float,
) -> dict[str, Any] | None:
    """A flag for a metric that moved too far from its 30-day baseline.

    A negative `threshold` means the rule watches for a *drop* (HRV), a positive one for a
    rise (resting HR, respiratory rate).
    """
    baseline = baselines.get((metric, Z_WINDOW))
    if baseline is None:
        return None
    value = getattr(summary, metric)
    raw_z = z_score(value, mean=baseline.mean, sd=baseline.sd, n=baseline.n)
    if raw_z is None:
        return None

    z = round(raw_z, Z_PRECISION)
    watches_drop = threshold < 0
    fired = z <= threshold if watches_drop else z >= threshold
    if not fired:
        return None

    direction = "below" if watches_drop else "above"
    return {
        "kind": kind,
        "metric": metric,
        "value": value,
        "z": z,
        "threshold": threshold,
        "detail": (
            f"{value:g} is {abs(z):g} SD {direction} your {Z_WINDOW}-day "
            f"baseline of {baseline.mean:.4g}."
        ),
    }


def _skin_temp_flag(
    summary: DailySummary, baselines: dict[tuple[str, int], Any]
) -> dict[str, Any] | None:
    """Skin temperature is compared in degrees, not SDs — half a degree is the signal."""
    baseline = baselines.get(("skin_temp_c", Z_WINDOW))
    if baseline is None or baseline.mean is None or summary.skin_temp_c is None:
        return None
    if summary.skin_temp_c < baseline.mean + SKIN_TEMP_RISE_C:
        return None
    return {
        "kind": "skin_temp_up",
        "metric": "skin_temp_c",
        "value": summary.skin_temp_c,
        "threshold": round(baseline.mean + SKIN_TEMP_RISE_C, 3),
        "detail": (
            f"Skin temperature {summary.skin_temp_c:.4g} °C is at least "
            f"{SKIN_TEMP_RISE_C} °C above your {Z_WINDOW}-day baseline."
        ),
    }


def _sleep_debt_flag(baselines: dict[tuple[str, int], Any]) -> dict[str, Any] | None:
    """The last week of sleep measured against the last quarter, not against a target.

    An absolute "8 hours" goal would be someone else's number; this asks whether *you* are
    sleeping less than you normally do.
    """
    recent = baselines.get(("sleep_duration_ms", 7))
    long_run = baselines.get(("sleep_duration_ms", 90))
    if recent is None or long_run is None or not recent.mean or not long_run.mean:
        return None
    ratio = recent.mean / long_run.mean
    if ratio >= SLEEP_DEBT_RATIO:
        return None
    return {
        "kind": "sleep_debt",
        "metric": "sleep_duration_ms",
        "ratio": round(ratio, 4),
        "threshold": SLEEP_DEBT_RATIO,
        "detail": (
            f"Your last 7 nights average {ratio:.0%} of your 90-day average sleep duration."
        ),
    }


def _bad_air_streak_flag(db: Session, day: date) -> dict[str, Any] | None:
    """Consecutive stale nights, counted backwards from `day`."""
    window_start = day - timedelta(days=BAD_AIR_NIGHTS - 1)
    nights = [
        value
        for value in db.execute(
            select(DailySummary.night_eco2_ppm_avg)
            .where(DailySummary.date >= window_start, DailySummary.date <= day)
            .order_by(DailySummary.date)
        )
        .scalars()
        .all()
        if value is not None
    ]
    # A night with no reading breaks the streak rather than being assumed clean.
    if len(nights) < BAD_AIR_NIGHTS or not all(v > BAD_AIR_ECO2_PPM for v in nights):
        return None
    return {
        "kind": "bad_air_streak",
        "metric": "night_eco2_ppm_avg",
        "nights": len(nights),
        "threshold": BAD_AIR_ECO2_PPM,
        "detail": (
            f"Night-time CO₂ has averaged over {BAD_AIR_ECO2_PPM:g} ppm for "
            f"{len(nights)} nights — try more ventilation."
        ),
    }


def _illness_warning(flags: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Two or more of the four physiological signals on the same day."""
    contributors = sorted({f["kind"] for f in flags} & set(ILLNESS_SIGNALS))
    if len(contributors) < ILLNESS_MIN_SIGNALS:
        return None
    return {
        "kind": "illness_warning",
        "contributors": contributors,
        "threshold": ILLNESS_MIN_SIGNALS,
        # Non-diagnostic by requirement: this describes the measurements, not a condition.
        "detail": (
            "Several of your overnight measurements moved together, which are signals "
            "consistent with strain on your system — consider taking it easy."
        ),
    }


# --------------------------------------------------------------------------
# Cards
# --------------------------------------------------------------------------
def card_key(kind: str) -> str:
    """The deterministic identity of the card a rule owns."""
    return kind if kind == "illness_warning" else f"anomaly:{kind}"


def _sync_cards(db: Session, flags: list[dict[str, Any]]) -> None:
    """Upsert a card per firing rule and expire the cards whose rule went quiet.

    Cards the owner dismissed are left alone in both directions — dismissal is a decision,
    not stale state, so a re-firing rule does not resurrect a card that was waved away.
    """
    firing = {flag["kind"]: flag for flag in flags}
    existing = {
        card.source_external_id: card
        for card in db.execute(
            select(InsightCard).where(
                InsightCard.source == DERIVED_SOURCE,
                InsightCard.kind.in_(_RULE_CARD_KINDS),
            )
        )
        .scalars()
        .all()
    }
    now = utcnow()

    for kind, flag in firing.items():
        key = card_key(kind)
        if key in existing and existing[key].status == _STATUS_DISMISSED:
            continue
        card, created = upsert(
            db,
            InsightCard,
            source=DERIVED_SOURCE,
            source_external_id=key,
            values={
                "kind": "illness_warning" if kind == "illness_warning" else "anomaly",
                "title": _TITLES.get(kind, kind),
                "body": flag["detail"],
                "metric_x": flag.get("metric"),
                "last_confirmed": now,
                "status": _STATUS_ACTIVE,
                "raw": flag,
            },
        )
        if created:
            card.first_seen = now

    active_keys = {card_key(kind) for kind in firing}
    for key, card in existing.items():
        if key not in active_keys and card.status == _STATUS_ACTIVE:
            card.status = _STATUS_EXPIRED
