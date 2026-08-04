"""The derived layer: reads the canonical store, writes derived tables.

Not a data source — there is nothing external to sync. It is a *consumer* that happens to
persist its results, so its writes go through the same idempotent `upsert()` every source
uses, keyed on a deterministic id. See `docs/decisions/0009-derived-layer-is-a-consumer.md`.

Modules:

* `dates` — which local day (or night) a canonical row belongs to (D1)
* `rollup` — canonical rows → one `daily_summary` row per date
* `readiness` — the transparent weighted readiness blend (§6)
* `baselines` — trailing 7/30/90-day mean + SD, and z-scores (§7)
* `flags` — anomaly rules + the illness early-warning, and their cards (§8)
* `jobs` — `run_daily_derivation()`: the whole pipeline, idempotent and self-healing (§5)
"""

#: Value written to `SourceRecord.source` on every derived row. Not a real source; it marks
#: rows as computed, so a re-derivation can find and update exactly its own output.
DERIVED_SOURCE = "derived"
