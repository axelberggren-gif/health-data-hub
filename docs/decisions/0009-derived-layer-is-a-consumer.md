# 0009 — The derived layer is a consumer, not a source

- **Status:** Accepted
- **Date:** 2026-08-04

## Context

V1 needs numbers that no device reports: a readiness score, "what is normal for me lately",
and flags for when a day looks off. Those are computed from data already in the canonical
store, but they have to be **stored** — the dashboard, the correlation engine (M4) and the
LLM brief (M5) all read the same daily rollup, and none of them should re-derive it from six
tables and a timezone rule.

That created a question the existing architecture did not answer. Everything that writes to
the store so far is a `HealthDataSource`: it subclasses `app/sources/base.py`, implements
`backfill()` / `sync_incremental()`, and maps a native payload into canonical models. The
derived layer has none of those properties — there is nothing external to sync, no
credentials, no pagination, no payload. Forcing it into the source contract would have meant
a source whose two required methods are lies.

The second question was idempotency. Invariant #2 says every write to a canonical table goes
through `upsert()` keyed on `(source, source_external_id)`. Derived rows are rewritten
constantly — a WHOOP sync at noon changes yesterday's numbers, and a laptop that slept for
three days recomputes a whole week on startup. Whatever wrote them had to be re-runnable
without duplicating anything.

## Decision

**`app/derived/` is a fourth kind of module: a consumer that persists.** It reads canonical
tables and writes derived ones (`daily_summary`, `baseline`, `insight_card`). It does *not*
implement `HealthDataSource` and is *not* in `app/sources/registry.py`, so
`/sync/{source}/...` cannot reach it. Its own entry points are the scheduler tick and
`POST /derived/run`.

**Its writes reuse the existing seam rather than inventing one.** Derived rows carry the
`SourceRecord` provenance columns with `source="derived"` and a *deterministic*
`source_external_id` — the ISO date for a daily summary, a finding key such as
`anomaly:hrv_drop` for a card — and go through `app.sync.orchestrator.upsert()`. The
`UniqueConstraint("source", "source_external_id")` is on the derived tables too, so the
database is still the backstop if anyone bypasses the write path. Recomputation is therefore
idempotent by construction, not by convention: running the job twice is a no-op
(`tests/test_derived_job.py::test_derivation_is_idempotent`).

`baseline` is the one exception and has no provenance mixin: it is a cache of a calculation
over `daily_summary`, keyed on `(metric, window)`, not a record of something that happened.

**Direction of dependency is one-way.** `app/derived/` imports from `app.models` and
`app.sync`; nothing in `app/sources/` may import from `app/derived/`. A source still may not
import `app.sync` — that invariant is unchanged, and the derived layer's licence to use
`upsert()` comes from it not being a source.

## Consequences

- Derived tables are safe to drop and rebuild: `run_daily_derivation` reproduces them from
  canonical data. That is what makes formula tuning cheap — change `readiness.py`, re-run,
  compare.
- A day with no upstream data gets **no** summary row rather than a row of nulls, so "the
  strap was on the charger" and "everything measured zero" stay distinguishable.
- Derived tables are deliberately **not** added to `EXPORT_MODELS`. An export is for data
  that would otherwise be lost; a derived row is reproducible from the rows already in it.
  The dashboard and JSON API (M6) are how these get read. Revisit if the owner ever wants a
  single file containing the conclusions as well as the evidence.
- `insight_card` lands here rather than in M4 as the tech spec sketched, because the illness
  early-warning (§8, an M2 deliverable) has to write one. M4 adds the correlation fields'
  first real use and the card lifecycle beyond active/expired.
- The reference day for baselines and flags is the newest date **with data**, not the
  calendar date. At 07:00 there may be no data for today yet, and judging a blank day
  against a month of real ones would produce a flag a day early, every day.
- The layer is a natural home for the future knowledge/insight compilation described in
  `SUPER_APP_PLAN.md`: same shape (read canonical, write derived, re-derivable).
