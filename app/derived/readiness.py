"""Readiness score v1 (tech spec §6) — a transparent weighted blend, **not** a model.

Three deliberate properties:

1. **Explainable.** Every score ships with the components and weights that produced it, so
   the dashboard and the LLM brief can always show the arithmetic instead of asserting a
   number.
2. **Renormalising.** A missing component (no air sensor before 2026-05-31) drops out and
   the remaining weights are rescaled. Treating it as zero would silently punish the score
   for a fact about the *hardware*.
3. **Never invented.** No usable recovery score means no readiness. `None` is a better
   answer than a confident guess.

Tuning the numbers here is a local edit plus its golden tests; adding a *component* changes
the shape of the score and belongs in the tech spec first.
"""

from __future__ import annotations

from typing import Any

#: Component weights. They only have to be relative — the score divides by the weights of
#: the components actually present.
WEIGHT_RECOVERY = 0.5
WEIGHT_SLEEP = 0.3
WEIGHT_ENVIRONMENT = 0.2

#: Air-quality penalties (see §6). Bands are two-sided: too cold is as bad as too warm.
ECO2_HIGH_PPM = 1000.0
ECO2_VERY_HIGH_PPM = 1400.0
ECO2_PENALTY = 25.0
ECO2_SEVERE_PENALTY = 40.0
TEMP_COMFORT_C = (16.0, 21.0)
TEMP_PENALTY = 15.0
HUMIDITY_COMFORT_PCT = (30.0, 60.0)
HUMIDITY_PENALTY = 10.0

#: How many decimals a readiness score keeps. More would be false precision on a heuristic.
_PRECISION = 1


def air_score(
    eco2_ppm_avg: float | None,
    temp_c_avg: float | None,
    humidity_pct_avg: float | None,
) -> float | None:
    """Score the night's bedroom air 0–100, or `None` if nothing was measured.

    Each dimension only subtracts when it was actually measured, so a sensor that reports
    CO2 but not humidity still contributes what it knows.
    """
    if eco2_ppm_avg is None and temp_c_avg is None and humidity_pct_avg is None:
        return None

    score = 100.0
    if eco2_ppm_avg is not None:
        if eco2_ppm_avg > ECO2_VERY_HIGH_PPM:
            score -= ECO2_SEVERE_PENALTY
        elif eco2_ppm_avg > ECO2_HIGH_PPM:
            score -= ECO2_PENALTY
    if temp_c_avg is not None and not (TEMP_COMFORT_C[0] <= temp_c_avg <= TEMP_COMFORT_C[1]):
        score -= TEMP_PENALTY
    if humidity_pct_avg is not None and not (
        HUMIDITY_COMFORT_PCT[0] <= humidity_pct_avg <= HUMIDITY_COMFORT_PCT[1]
    ):
        score -= HUMIDITY_PENALTY

    # Defensive: keeps future penalty tuning from ever producing a negative score.
    return max(0.0, score)


def compute_readiness(
    *,
    recovery_score: float | None,
    user_calibrating: bool | None,
    sleep_performance_pct: float | None,
    environment_score: float | None,
) -> tuple[float | None, list[dict[str, Any]] | None]:
    """Return `(readiness, components)` — both `None` when recovery is unusable.

    A WHOOP score from a still-calibrating strap counts as missing: it is a placeholder, not
    a measurement, and blending it in would make the first weeks of data look like signal.
    """
    if recovery_score is None or user_calibrating:
        return None, None

    components: list[dict[str, Any]] = [
        {"component": "recovery", "value": float(recovery_score), "weight": WEIGHT_RECOVERY}
    ]
    if sleep_performance_pct is not None:
        components.append(
            {
                "component": "sleep",
                "value": float(sleep_performance_pct),
                "weight": WEIGHT_SLEEP,
            }
        )
    if environment_score is not None:
        components.append(
            {
                "component": "environment",
                "value": float(environment_score),
                "weight": WEIGHT_ENVIRONMENT,
            }
        )

    total_weight = sum(c["weight"] for c in components)
    weighted = sum(c["value"] * c["weight"] for c in components)
    return round(weighted / total_weight, _PRECISION), components
