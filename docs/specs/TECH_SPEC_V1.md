# Technical Specification — Super-App V1 ("Unify & See + First Insights")

> **Status:** Draft for implementation · **Date:** 2026-07-02 · **Supersedes nothing** —
> this spec *implements* the V1 scope locked in `SUPER_APP_PLAN.md` (§ "Decisions & scope —
> locked 2026-06-23"). If this spec and the plan disagree on scope, the plan's locked
> decisions win; if this spec and reality disagree during implementation, update this spec
> in the same PR (canon rule).

This document is written so that **any AI coding agent can pick it up cold and build V1**,
milestone by milestone, without needing the original conversation. Read `AGENTS.md` first —
its invariants and workflow (branch naming, PR-only merges, `make check`, CHANGELOG, ADRs
for seam changes) apply to every milestone here and are not restated in full.

**Companion document:** `docs/specs/TEST_SPEC_V1.md` defines the numbered test cases
(M0-T01 … M6-T05) that each milestone must implement **before** feature code is written
(tests-first, same PR — see its "How to use" section). A milestone is accepted only when
all of its test cases pass; the criteria tables below reference them by ID.

---

## 1. Scope

### In scope (V1, from the locked plan)

| Area | Items |
|---|---|
| Derived layer | Nightly daily-summary rollups, 7/30/90-day personal baselines, anomaly flags |
| Dashboard (PWA) | B1 Today view · B2 unified readiness score · B3 trends + anomalies · B4 day timeline · B5 refreshed cross-source reports |
| Cheap inputs | A3 daily check-in · A5 alcohol/caffeine · A10 supplements (one combined "daily log") · A4 weather/daylight (auto, free API) |
| Insights | C2 correlation cards · C5 illness early-warning · C6 training-load (WHOOP-only) · C1 daily brief (Claude) · C3 ask-anything (Claude) |
| Schema reservations | `biomarker`, `intake_event`, `nutrition_entry` tables created empty (plan §3) |

### Out of scope (V1)

Strava, Apple Health / Sleep Cycle, Google Calendar, push notifications, email digests,
voice, experiments (E1), goals (E2), the Phase-5 sensing app, any multi-user support, and
any non-local hosting. Locked decisions: **client = responsive web app (PWA)**, **hosting =
local Mac**, **LLM = Claude API behind a model-agnostic seam**.

### Non-goals / guardrails

- No raw health data is ever sent to the LLM — only pre-computed summary features (§10).
- No personal data or secrets in tracked files; the repo is public (see `AGENTS.md`).
- Nothing in this spec changes the existing source seam (`app/sources/base.py`) or the
  upsert contract (`app/sync/orchestrator.py`). New layers *consume* the canonical store.

---

## 2. Current system (what you build on)

- **Stack:** Python 3.12+, FastAPI, SQLAlchemy 2.0 (`Mapped[...]`), Pydantic v2 /
  pydantic-settings, httpx. SQLite (`health.db`) by default; Postgres via `DATABASE_URL`.
- **Data flow:** source adapter (`app/sources/*`) → canonical store (`app/models.py`) →
  consumers (`app/export/`). All writes go through
  `app.sync.orchestrator.upsert(db, Model, source=…, source_external_id=…, values=…)`,
  deduped by `(source, source_external_id)`; the caller commits.
- **Live data:** WHOOP (`source="whoop_api"`): `recovery_daily`, `sleep_session` (+
  `sleep_stage`), `workout`, `cycle_day`, `profile`, `body_measurement` — ~6 months.
  Mill (`source="mill_sense"`): `air_quality_reading` — polled snapshots (temp, humidity,
  TVOC, eCO₂), one row per poll-minute, `recorded_at` = poll time.
- **App wiring:** `app/main.py` mounts routers from `app/api/`; lifespan runs `init_db()`
  (dev `create_all`) and optionally starts the Mill poller (`app/scheduler.py`).
- **Config:** everything via `Settings` in `app/config.py` (`get_settings()`), env/`.env`.

### New packages this spec adds

```
app/derived/            # day attribution, rollups, baselines, readiness, flags (M1, M2)
  dates.py              # D1 day attribution (M1)
  jobs.py               # run_daily_derivation(db, days_back, today=None) — the daily job
  rollup.py             # canonical rows -> DailySummary values
  baselines.py          # 7/30/90-day baselines + z-scores
  readiness.py          # readiness score v1
  flags.py              # anomaly + illness-warning rules (sketched as anomalies.py; named
                        # flags.py to match daily_summary.flags, which it writes)
app/insights/           # statistics + LLM (M4, M5)
  correlations.py       # C2
  training_load.py      # C6
  llm.py                # LLMProvider seam + ClaudeProvider
  brief.py              # C1 daily brief
  ask.py                # C3 ask-anything
app/sources/manual/     # A3/A5/A10 check-in + intake as a normal source (M3)
app/sources/weather/    # A4 Open-Meteo adapter (M3)
app/api/routes_dashboard.py   # JSON endpoints for the PWA
app/api/routes_log.py         # POST endpoints for the daily log
app/api/routes_insights.py    # brief / ask / cards
web/                    # the PWA (templates + static, served by FastAPI) (M6)
alembic/                # migrations (M0)
```

Each new package gets its own `CLAUDE.md` (purpose, key files, invariants) in the PR that
creates it — same style as the existing ones.

---

## 3. Foundational decisions (read before coding)

These resolve ambiguities the plan left open. Each was chosen for the single-user,
local-first V1; revisit via ADR if the context changes.

### D1 — The "day" and timezones

Daily rollups need an unambiguous day key. Rules:

1. `Settings.home_timezone` (default `"Europe/Stockholm"`, IANA name) defines the local
   calendar. All `date` keys in derived tables are local dates in this zone.
2. **Sleep** attributes to the **wake date**: the local date of `sleep_session.end`
   (naps excluded from nightly rollups; `nap == True` rows are ignored for readiness and
   baselines but still shown on the B4 timeline).
3. **Recovery** attributes to the wake date of its linked sleep when resolvable
   (`recovery_daily.sleep_id` → `sleep_session.source_external_id`), else the local date
   of `recorded_at`.
4. **Cycle/strain and workouts** attribute to the local date of their `start`.
5. **Air quality**: two aggregations — (a) *night window*: readings between the night's
   sleep `start` and `end` (this feeds readiness), and (b) *local-date* daily aggregate
   (for trends). If no sleep session exists for a date, (a) is null.
6. Per-record `timezone_offset` strings are ignored for day bucketing in V1 (single user,
   single home zone); they are preserved in the store for a future travel-aware pass (E3).

### D2 — The derived layer is a consumer, not a source

`app/derived/` and `app/insights/` **read** canonical tables and **write** derived tables.
They do not implement `HealthDataSource` (nothing external to sync). Their writes reuse
`upsert()` with `source="derived"` and a deterministic `source_external_id` (e.g. the ISO
date), so recomputation is idempotent by construction and the existing invariant #2 holds
everywhere. This is a new architectural layer → **add an ADR** describing it in the M2 PR.
(This spec originally said "ADR 0006"; 0006–0008 were taken before M2 started. It landed as
**ADR-0009**.)

### D3 — Manual input *is* a source

The daily log (A3/A5/A10) enters through `app/sources/manual/` implementing
`HealthDataSource` (`capabilities() = {"checkin", "intake"}`; `backfill`/`sync_incremental`
are no-ops returning empty `SyncResult`s — the data arrives via POST, analogous to
`handle_webhook`). The API route hands payloads to the source, which maps → canonical
models via `upsert()`. Identity: check-ins key on the local date
(`source_external_id = "checkin:2026-07-02"`, so re-submitting edits the same row);
intake events key on a client-generated UUID.

### D4 — Migrations (Alembic) before any schema change

`app/db.py` says "production uses Alembic" but Alembic is not installed or configured —
and this spec adds ~10 tables. **M0 fixes this first.** Rule after M0: brand-new tables may
still ride `init_db()`/`create_all` in dev, but every schema change ships with an Alembic
revision, and CI runs `alembic upgrade head` against a scratch SQLite DB to prove
migrations replay. Never edit an existing table without a migration.

### D5 — Frontend stack: server-rendered + htmx, no Node toolchain

The PWA is FastAPI + Jinja2 templates + [htmx](https://htmx.org) for interactivity +
Chart.js for charts, with **all JS/CSS vendored** into `web/static/` (no CDN at runtime —
the PWA must work offline-ish, and pinned local assets keep the public repo reproducible).
Rationale: keeps CI single-language (ruff/mypy/pytest already cover everything), no build
step, and AI agents iterate fastest on server-rendered HTML. A PWA `manifest.json` + a
minimal cache-shell service worker make it installable on the phone. If V2 outgrows this,
switching to a SPA is an ADR, not a rewrite (the JSON API in §11 is the contract either way).

### D6 — Auth from day one (cheap now, painful later)

Even local-only, the dashboard exposes health data over HTTP. A single shared bearer token
(`Settings.app_token`, empty ⇒ auth disabled for dev) guards `/dashboard`, `/log`,
`/insights`, and `/export` routes via one FastAPI dependency. The PWA stores it once
(cookie set on first visit with `?token=…`). When hosting moves off-localhost (V2), this
upgrades to a real session — but no route ships unauthenticated-by-design.

### D7 — Weather location

A4 needs coordinates but auto-location (A12) is gated to Phase 5. V1 uses static
`Settings.home_lat` / `home_lon` (floats, default 0.0 ⇒ weather source disabled).
Provider: **Open-Meteo** (free, no API key, includes daily sunrise/sunset/daylight,
historical + forecast). One request per sync day; defensive parsing in the adapter.

---

## 4. Data model additions

All tables follow existing conventions (`from __future__ import annotations`, `Mapped[...]`,
`UniqueConstraint("source", "source_external_id")` where `SourceRecord` is mixed in).
Ship in the milestone noted; every table lands with an Alembic revision (D4).

### `daily_summary` (M2) — `SourceRecord` mixin, one row per local date

`source="derived"`, `source_external_id=<ISO date>`.

| Column | Type | Notes |
|---|---|---|
| `date` | Date, unique, index | local date (D1) |
| `recovery_score`, `hrv_rmssd_ms`, `resting_hr_bpm`, `spo2_pct`, `skin_temp_c` | Float? | from that date's recovery |
| `sleep_performance_pct`, `sleep_efficiency_pct`, `sleep_duration_ms`, `sleep_debt_ms`, `rem_ms`, `slow_wave_ms`, `respiratory_rate`, `disturbance_count` | Float?/Int? | from the night's main sleep |

`sleep_duration_ms` is time *asleep* (light + slow-wave + REM), not time in bed. `sleep_debt_ms`
required a canonical addition in M2 — `sleep_session.sleep_debt_ms`, mapped from WHOOP's
`score.sleep_needed.need_from_sleep_debt_milli` — because reading it out of `raw` here would
leak a source payload shape into the derived layer (global invariant #3).
| `day_strain`, `workout_count`, `workout_strain_sum`, `kilojoule` | Float?/Int? | from cycle + workouts |
| `night_temp_c_avg`, `night_eco2_ppm_avg`, `night_eco2_ppm_max`, `night_tvoc_ppb_avg`, `night_humidity_pct_avg` | Float? | night-window air (D1.5a) |
| `weather_temp_min_c`, `weather_temp_max_c`, `daylight_seconds`, `sunrise`, `sunset` | Float?/Int?/DateTime? | from weather source |
| `checkin_mood`, `checkin_energy`, `checkin_stress`, `checkin_soreness` | Int? | 1–5, from check-in |
| `alcohol_units`, `caffeine_after_14`, `last_caffeine_at` | Float?/Bool?/DateTime? | from check-in |
| `readiness_score` | Float? | §6 |
| `readiness_components` | JSON? | inputs + weights actually used (explainability) |
| `flags` | JSON? | list of anomaly/warning dicts (§8) |

### `baseline` (M2) — no mixin; recomputed in place

Unique on `(metric, window)`. Columns: `metric` (str, e.g. `"hrv_rmssd_ms"`), `window`
(int: 7/30/90), `mean`, `sd`, `n`, `computed_at`. Baselines always **exclude today** and
use trailing complete days.

### `checkin_daily` (M3) — `SourceRecord` mixin, source `"manual"`

`date` (unique), `mood`, `energy`, `stress`, `soreness` (Int 1–5, all nullable),
`alcohol_units` (Float?), `last_caffeine_at` (DateTime?), `note` (String?).

### `intake_event` (M3) — `SourceRecord` mixin, source `"manual"` (plan §3 reservation, but used immediately for A10)

`ts` (DateTime, index), `name` (String), `kind` (String: `vitamin|supplement|medication`),
`dose` (Float?), `unit` (String?).

### `weather_daily` (M3) — `SourceRecord` mixin, source `"open_meteo"`

`date` (unique per source), `temp_min_c`, `temp_max_c`, `precipitation_mm`,
`sunrise`, `sunset`, `daylight_seconds`, `pollen_index` (Float?, null — Open-Meteo pollen
is regional; fill if available).

### `insight_card` (**landed in M2**, was planned for M4) — `SourceRecord` mixin, source `"derived"`

Moved earlier because §8 — an M2 deliverable — has to write the illness-warning card. M2 fills
`kind` / `title` / `body` / `metric_x` / `first_seen` / `last_confirmed` / `status`; the
statistics fields below are M4's.

`kind` (String: `correlation|illness_warning|training_load|anomaly`), `title` (String),
`body` (String), `metric_x`/`metric_y` (String?), `effect_size` (Float?), `n` (Int?),
`p_value` (Float?), `lag_days` (Int?), `first_seen` / `last_confirmed` (DateTime),
`status` (String: `active|expired|dismissed`). `source_external_id` = deterministic key
(e.g. `"corr:alcohol_units:hrv_rmssd_ms:lag1"`) so re-running the engine updates rather
than duplicates cards.

### Reserved, created empty (M3): `biomarker`, `nutrition_entry`

Exactly as sketched in `SUPER_APP_PLAN.md` §3 (columns listed there). No API, no UI in V1 —
the point is that adding labs/food later is an adapter + a form, not a migration scramble.

---

## 5. Derivation job (M2)

`app/derived/jobs.py::run_daily_derivation(db, days_back: int = 7, *, today: date | None = None)`:

1. For each of the last `days_back` local dates (oldest first): recompute the full
   `daily_summary` row from canonical tables and upsert it (D2). A date with **no** upstream
   data is skipped rather than written as a row of nulls, so "the strap was charging" and
   "everything measured zero" stay distinguishable.
2. Recompute all `baseline` rows (7/30/90 windows) from `daily_summary`.
3. Re-evaluate anomaly + illness rules (§8) for the **newest date that has data** — not
   necessarily the calendar today, which may still be empty at 06:00 — and update `flags` and
   `insight_card` rows.
4. Commit once at the end; return a `SyncResult`-like report (counts per step).

`today` pins the last date of the window (default: the local today) so a historical window can
be backfilled deliberately.

**Scheduling & catch-up:** hosting is a laptop that sleeps, so the job must never assume it
ran yesterday. It is (a) exposed as `POST /derived/run?days_back=N`, (b) registered in the
existing scheduler (`app/scheduler.py`) to run daily at `DERIVED_RUN_HOUR` local (default 06)
*and* once on app startup if the newest `daily_summary` is stale (> 24 h old), with the window
widened to cover the whole gap so missed days self-heal. `DERIVED_SCHEDULE_ENABLED=false`
switches the tick off. Late-arriving source data (a WHOOP sync at noon) is picked up the
next run; `POST /derived/run` lets the UI offer a manual "refresh" button.

**Determinism:** rollup functions are pure (`rows -> values`), unit-testable with golden
fixtures. Running the job twice in a row must be a no-op (idempotency test required).

---

## 6. Readiness score v1 (B2)

A transparent weighted blend — **not** a model. For date *d*:

| Component | Value (0–100) | Weight |
|---|---|---|
| `recovery` | WHOOP `recovery_score` as-is | 0.5 |
| `sleep` | WHOOP `sleep_performance_pct` as-is | 0.3 |
| `environment` | air score: start at 100; −25 if `night_eco2_ppm_avg` > 1000 (−40 if > 1400); −15 if `night_temp_c_avg` outside 16–21 °C; −10 if `night_humidity_pct_avg` outside 30–60 % | 0.2 |

`readiness = Σ(component × weight) / Σ(weights of components present)` — missing
components (e.g. no Mill data before 2026-05-31) drop out and weights renormalize.
If *recovery* itself is missing, readiness is null (don't fake it). Days with
`user_calibrating == True` recovery are treated as missing. Store the actual components
and weights used in `readiness_components` so the UI and the LLM can always explain the
number. Tuning the formula later = editing `readiness.py` + its golden tests; changing its
*shape* (new component) = note in this spec.

---

## 7. Trends & baselines (B3)

- Baselines: trailing 7/30/90-day mean + SD per metric (metrics: hrv, rhr, recovery,
  sleep duration, sleep performance, respiratory rate, skin temp, spo2, strain, readiness,
  night eCO₂/temp), always **excluding the day being judged**. The SD is a *population* SD: a
  window is the complete set of days it covers, not a sample from a larger pool, and it keeps
  the §8 thresholds exact rather than estimator-dependent.
- A metric's **z-score for today** = (today − 30d mean) / 30d SD (require n ≥ 14, SD > 0), and
  §8 compares it rounded to 3 decimals so a value on the threshold fires deterministically.
- The trends view (B3) charts metric + 7d rolling mean + 30d band (±1 SD), over a
  selectable 30/90/180-day range.

## 8. Anomaly flags & illness early-warning (C5)

Rule-based, evaluated on the newest complete day; each firing rule appends a dict to
`daily_summary.flags` and upserts an `insight_card`:

- `hrv_drop`: HRV z ≤ −1.5 · `rhr_elevated`: RHR z ≥ +1.5 · `resp_rate_up`: resp z ≥ +1.5
  · `skin_temp_up`: skin temp ≥ 30d mean + 0.5 °C · `sleep_debt`: 7d sleep duration mean
  < 90 % of 90d mean · `bad_air_streak`: night eCO₂ avg > 1000 ppm for ≥ 3 nights.
- **Illness early-warning** (`illness_warning` card): fires when ≥ 2 of
  {`hrv_drop`, `rhr_elevated`, `resp_rate_up`, `skin_temp_up`} fire on the same day —
  wording must be non-diagnostic ("signals consistent with strain on your system —
  consider taking it easy"), never a medical claim.

## 9. Correlation engine (C2) — statistics with guardrails

~180 days × many variables ⇒ multiple-comparisons false positives are *guaranteed* without
discipline. An insight engine that surfaces spurious correlations kills trust immediately,
so these guardrails are part of the contract, not polish:

- **Variable list (explicit, curated):** inputs = {alcohol_units, last-caffeine-after-14h,
  night eCO₂ avg, night temp avg, day strain, late-workout (end after 20:00), daylight
  seconds, mood/energy/stress/soreness, supplement taken (per distinct `name` with ≥ 15
  events)}; outcomes = {HRV, RHR, recovery, sleep duration, REM ms, deep ms, sleep
  efficiency, respiratory rate, readiness}.
- **Method:** Spearman correlation on daily pairs at lags 0 and 1 (input on day *d* vs
  outcome on *d* or *d+1* — e.g. alcohol tonight → tomorrow's HRV). Implement with
  `scipy.stats.spearmanr` (add `scipy` to `requirements.txt`).
- **Publication gates (all required):** overlapping n ≥ 30 · |ρ| ≥ 0.25 ·
  Benjamini–Hochberg FDR at q = 0.05 across *all* pairs tested in the run · effect
  phrased in natural units where computable (median-split difference: "nights after
  alcohol: −18 ms HRV vs. nights without").
- Cards carry `n`, `effect_size`, `p_value`, `lag_days`; re-runs update existing cards
  (deterministic key, §4); a card whose correlation no longer passes gates flips to
  `expired`, not deleted.
- Correlation ≠ causation: card copy uses "is associated with", and the UI shows n.

## 10. LLM seam + daily brief (C1) + ask-anything (C3)

### The seam (`app/insights/llm.py`)

```python
class LLMProvider(ABC):
    @abstractmethod
    def complete(self, system: str, user: str, max_tokens: int = 1024) -> str: ...
```

`ClaudeProvider(LLMProvider)` calls the Anthropic Messages API via `httpx` (or the
`anthropic` SDK — implementer's choice; add the dep to `requirements.txt`). Config:
`Settings.anthropic_api_key` (empty ⇒ LLM features return HTTP 503 with a clear message —
the app must run fine without a key), `Settings.llm_model` (default a current small model,
e.g. Haiku-class; keep it a setting, not a constant), `Settings.llm_daily_token_cap`
(default 50_000; a simple counter in a small `llm_usage` table or in-memory per-day guard
refuses calls past the cap). Provider selection by `Settings.llm_provider` (default
`"claude"`) so a local model can slot in later (locked decision).

### Privacy contract (invariant — the AI reviewer should block violations)

Prompts may contain **only**: derived features (`daily_summary` fields, baselines,
z-scores, flags, insight cards) and coarse aggregates. **Never**: `raw` payloads, `Profile`
(name/email), tokens, or row-level dumps of canonical tables. Build one function
`build_feature_context(db, days) -> dict` that whitelists fields explicitly — both C1 and
C3 go through it. Log token counts, never prompt contents.

### C1 — daily brief

`GET /insights/brief` (and shown on the Today view): 3–4 sentences — last night, today's
readiness + why (components), one concrete suggestion tied to an active flag/card. Cache
per date in a `daily_brief` table (date unique, text, model, created_at) so repeated views
cost zero tokens; `?refresh=true` regenerates.

### C3 — ask-anything

`POST /insights/ask {question: str}`: answers over `build_feature_context` (last 90 days
of summaries + active cards + baselines). V1 is single-turn (no conversation memory).
System prompt states: personal data, be quantitative, cite which features were used, no
medical diagnoses.

## 11. API surface (all JSON under the D6 auth dependency)

| Route | Purpose |
|---|---|
| `GET /dashboard/today` | newest `daily_summary` + readiness components + active flags/cards + brief-if-cached |
| `GET /dashboard/trends?metrics=…&days=90` | series + rolling stats for B3 |
| `GET /dashboard/day/{date}` | B4 timeline: that day's sleep window + stages, workouts, hourly air readings, check-in, weather |
| `GET /dashboard/cards` | active insight cards (B5/C2) |
| `POST /log/checkin` | upsert today's (or `?date=`) check-in (D3) |
| `POST /log/intake` | append an intake event |
| `POST /derived/run?days_back=7` | run the derivation job now |
| `GET /insights/brief`, `POST /insights/ask` | §10 |

The PWA pages (`/`, `/trends`, `/day/{date}`, `/log`) are server-rendered views over the
same data; htmx posts hit the routes above.

## 12. PWA (M6) — pages

1. **Today (B1):** readiness dial + component breakdown, last-night sleep card, recovery
   card, night-air card, weather/daylight, active flags & insight cards, the daily brief,
   and the daily-log form (A3/A5/A10 as one quick form: 4 sliders, alcohol stepper,
   caffeine time, supplement checkboxes from recent `name`s + free-text add).
2. **Trends (B3):** metric picker, Chart.js line + baseline band, anomaly markers.
3. **Day (B4):** vertical timeline for a chosen date (sleep bar with stages, workouts,
   air-quality sparkline, intake events, check-in).
4. **Ask (C3):** one text box, streamed-or-not answer, last few Q&As from local storage.

Installable: `manifest.json`, icons, service worker caching the static shell only (never
API responses — health data stays out of cache storage). Mobile-first layout (this is a
phone app in practice). B5: the old `bedroom_air_vs_sleep.html` analysis becomes a
"reports" section fed by `/dashboard/trends` — regenerated live, not a committed artifact.

## 13. Milestones

Each = one PR (or a few small ones), branched per `AGENTS.md`, `make check` green,
CHANGELOG + touched `CLAUDE.md`s updated. **Tests come first:** the PR's opening commit
implements the milestone's test cases from `TEST_SPEC_V1.md` (red), then implementation
makes them pass (green) — see that document's binding workflow rules. Acceptance criteria
below are the definition of done. **Recommended order is strict** — each builds on the
previous.

| # | Deliverable | Test cases (must pass) | Acceptance criteria |
|---|---|---|---|
| **M0** | Alembic + config + auth stub | M0-T01 … M0-T05 | `alembic upgrade head` recreates the current schema on a fresh DB; CI proves it. New `Settings` fields (home_timezone, home_lat/lon, app_token, anthropic_api_key, llm_*) with safe defaults + `.env.example` updated. Auth dependency exists (no routes newly broken when token unset). ADR if any seam interpretation was needed. |
| **M1** | Day-attribution module (D1) | M1-T01 … M1-T08 | `app/derived/dates.py` pure functions mapping each canonical row type → local date / night window; `tests/factories.py` fixture builders land here. |
| **M2** | Derived layer + job (§5–§8) | M2-T01 … M2-T11 | `daily_summary` + `baseline` tables via migration; derivation idempotent; readiness renormalizes on missing components; flags fire at exact thresholds; scheduler + startup catch-up wired; the derived-layer ADR (D2) added. |
| **M3** | Manual + weather sources; reserved tables | M3-T01 … M3-T09 | `manual` + `open_meteo` registered in the registry; check-in/intake upsert by key; weather backfills 6 months and syncs incrementally with a cursor; `biomarker`/`intake_event`/`nutrition_entry` exist; no real network in tests. |
| **M4** | Statistics insights (C2, C6) | M4-T01 … M4-T06 | Correlation engine finds planted correlations and publishes nothing on null data; FDR unit-tested; card lifecycle deterministic; training-load card on the Today payload. |
| **M5** | LLM seam + brief + ask (C1, C3) | M5-T01 … M5-T06 | Provider seam + Claude impl; app fully functional with no API key (503 on LLM routes only); privacy whitelist enforced (M5-T02 is a release blocker); brief cached per date; token cap enforced. |
| **M6** | PWA dashboard | M6-T01 … M6-T05 | All four pages render on mobile viewport; installable (manifest + SW, static shell only cached); daily log round-trips into next derivation; vendored assets only; auth honored. |

Rough sizing: M0–M2 are the load-bearing half; M6 is the most iterative. A capable agent
should treat each milestone as an independent session with this spec, `TEST_SPEC_V1.md`,
and `AGENTS.md` as input.

## 14. Testing requirements (beyond the per-milestone catalog)

- **The test catalog is the contract.** `docs/specs/TEST_SPEC_V1.md` enumerates every
  required case with fixtures and expected values; implement them tests-first (its rules
  1–5 are binding, including the traceability docstring `"""Mx-Tyz: …"""` on every test).
- All new tests follow `tests/CLAUDE.md` rules: hermetic, temp SQLite, no network, no real
  credentials. Shared fixture builders live in `tests/factories.py` (specified in the test
  spec's rule 5, built in M1).
- Idempotency is the house invariant: every new write path (derivation, check-in, weather,
  cards, brief cache) has a run-twice test in the catalog; any write path added beyond the
  catalog gets one too.
- Statistical code gets synthetic-data tests with known answers, not snapshot tests.
- If a catalog case turns out wrong during implementation, amend `TEST_SPEC_V1.md` in the
  same PR with a one-line justification — never silently skip or delete a case.

## 15. Deferred decisions (explicitly not decided here)

- Hosting move (Fly.io/Render + Postgres) and push notifications — V2, revisit D6 then.
- Travel/timezone-aware day attribution (uses stored `timezone_offset`) — with E3.
- `vitals_timeseries` has no unique constraint and no writer yet; define its identity
  key before the first writer lands (flagged during plan review).
- Readiness formula tuning beyond §6 — after ≥ 30 days of side-by-side observation.
