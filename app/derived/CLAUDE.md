> **Canon** — current source of truth for this directory. If reality and this file disagree,
> fix this file in the same PR.

# app/derived/ — the derived layer (rollups, baselines, readiness, anomalies)

## Purpose
Turn the canonical store into the **daily** shape the dashboard, insights and the LLM read:
one row per local date, personal baselines, a readiness score, and anomaly flags. This layer
is a **consumer, not a source** (TECH_SPEC_V1 D2): it reads canonical tables and writes
derived tables — it does not implement `HealthDataSource` because there is nothing external
to sync.

## Key files
- `dates.py` — day attribution (D1). Pure functions: `local_date`, `sleep_wake_date`,
  `event_local_date`, `attribute_recovery`, `night_sleep_for_date`, `night_window`,
  plus the `as_utc` naive-is-UTC helper. Everything downstream keys off these, so a bug
  here misbuckets every derived row.
- (M2) `rollup.py`, `baselines.py`, `readiness.py`, `anomalies.py`, `jobs.py`.

## Conventions
- The local calendar is `Settings.home_timezone` — never `date.today()` on server time and
  never UTC bucketing. Functions take an optional `tz` override so tests can be explicit.
- **Naive datetimes are read as UTC.** SQLite hands `DateTime(timezone=True)` values back
  without a `tzinfo`; the store only ever holds UTC instants, so `as_utc()` restores them.
  Always normalise to UTC *before* binding a datetime into a query.
- Per-record `timezone_offset` strings are ignored for day bucketing in V1 (single user,
  single home zone — D1.6); they stay in the store for a future travel-aware pass.
- Rollup functions stay pure (`rows -> values`) so they are unit-testable with golden
  fixtures; only `jobs.py` touches transactions.

## Invariants (do not break)
- Sleep attributes to its **wake** date; naps (`nap == True`) are never the night's sleep.
  Cycles and workouts attribute to the local date of `start`. Recovery follows its linked
  sleep when resolvable, else `recorded_at`.
- No night sleep for a date ⇒ `night_window()` is `None` ⇒ **no** night-air aggregate.
  Never silently widen to the whole calendar day.
- (M2) Every derived write goes through `upsert()` with `source="derived"` and a
  deterministic `source_external_id` (the ISO date), so recomputation is idempotent.

## Recent changes
- V1 M1: created the package with `dates.py` (day attribution per D1) and the shared test
  fixture builders in `tests/factories.py`. Tests M1-T01 … M1-T08.
