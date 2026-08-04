"""The derived layer: rollups, baselines, readiness and anomalies over the canonical store.

A **consumer**, not a source (tech spec D2) — it reads canonical tables and writes derived
ones. It implements no `HealthDataSource`, because there is nothing external to sync.
"""
