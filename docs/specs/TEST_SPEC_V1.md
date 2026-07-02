# Test Specification — Super-App V1 (companion to TECH_SPEC_V1.md)

> **Status:** Draft for implementation · **Date:** 2026-07-02
> Every test case here is written **before** its feature exists. A milestone is done when
> every one of its test cases is implemented in `tests/` and passing — the test IDs below
> are the acceptance contract that generated code is verified against.

## How to use this document (TDD workflow — binding)

1. **Tests first, same PR.** Each milestone PR's *first commit* adds that milestone's test
   cases from this catalog (red). Implementation commits follow until green. `main` only
   ever sees the green end state (PRs are the only path to `main`), but the PR history
   must show tests preceding implementation.
2. **Traceability.** Every implemented test carries its ID in the docstring, e.g.
   `"""M2-T04: readiness renormalizes when the air component is missing."""` One catalog
   case may map to several parametrized tests, but every ID must appear at least once.
   Reviewer rule (human or AI): an implementation PR whose diff touches a milestone's
   modules but lacks its test IDs is incomplete.
3. **House rules apply** (`tests/CLAUDE.md`): hermetic, temp SQLite via `conftest.py`, no
   real network (mock `httpx`), no real credentials, distinct `source_external_id`s per
   test. Statistical tests use synthetic data with *known* answers — never snapshots.
4. **Deviations.** If implementation legitimately invalidates a case (an expected value
   was wrong, a signature changed), update this file **in the same PR** with one line of
   justification — never silently skip a case.
5. **Shared fixtures** (built in M1–M2, reused everywhere): `tests/factories.py` with
   builders that return committed canonical rows with sensible defaults, overridable per
   test: `make_sleep(db, *, end, start=None, nap=False, performance=80.0, …)`,
   `make_recovery(db, *, score=60.0, sleep_id=None, hrv=55.0, rhr=52.0, …)`,
   `make_cycle(db, …)`, `make_workout(db, …)`, `make_air_reading(db, *, recorded_at,
   eco2=800.0, temp=19.0, humidity=45.0, …)`, `make_checkin(db, …)`,
   `make_summary(db, *, date, …)` (direct `daily_summary` rows for baseline/stats tests).
   All timestamps below are **Europe/Stockholm local** unless suffixed `UTC`.

---

## M0 — Alembic, config, auth stub

| ID | Test case |
|---|---|
| **M0-T01** | **Migrations recreate the schema.** Given an empty temp SQLite DB, when `alembic upgrade head` runs against it, then the resulting table set and columns equal `Base.metadata` (compare via SQLAlchemy `inspect`; assert no missing/extra tables, and per-table no missing/extra columns). |
| **M0-T02** | **Settings defaults are safe.** With no env vars set (isolated env), `Settings()` loads with `home_timezone == "Europe/Stockholm"`, `home_lat == 0.0`, `home_lon == 0.0`, `app_token == ""`, `anthropic_api_key == ""`, `llm_provider == "claude"`, `llm_daily_token_cap == 50_000` — and the app still boots (TestClient `GET /health` → 200). |
| **M0-T03** | **Auth disabled when token unset.** With `app_token == ""`, a request to a protected route (use `GET /export`-family or a dedicated probe route) returns non-401. |
| **M0-T04** | **Auth enforced when token set.** With `app_token == "test-token-123"`: no `Authorization` header → 401; `Bearer wrong` → 401; `Bearer test-token-123` → non-401. Parametrize over every protected router prefix (`/dashboard`, `/log`, `/insights`, `/export`) as those routes land — extend this test in later milestones, don't duplicate it. |
| **M0-T05** | **Existing suite unaffected.** The pre-existing smoke + idempotency tests pass unchanged (no fixture edits needed beyond `conftest.py` env isolation for M0-T02). |

## M1 — Day attribution (`app/derived/dates.py`, pure functions)

Assumed API (adjust names in the same PR if implementation differs, per rule 4):
`sleep_wake_date(end_utc, tz) -> date`, `attribute_recovery(recovery_row, db) -> date`,
`event_local_date(start_utc, tz) -> date`, `night_window(db, date) -> tuple[dt, dt] | None`.

| ID | Test case |
|---|---|
| **M1-T01** | Sleep ending 2026-06-10 07:12 local → wake date `2026-06-10`. |
| **M1-T02** | Sleep 2026-06-09 22:30 → 2026-06-10 06:40 (crosses midnight) → `2026-06-10`. |
| **M1-T03** | Nap (`nap=True`, 14:00–15:00) is excluded: the nightly-sleep selector for that date returns the night session only; with *only* a nap present it returns `None`. |
| **M1-T04** | **Timezone conversion, not UTC bucketing.** Sleep end stored `2026-06-09 23:30 UTC` (= 01:30 local CEST) → wake date `2026-06-10`. |
| **M1-T05** | **DST transitions don't crash or misbucket.** Sleep spanning the CET→CEST spring-forward night (2026-03-29 01:30 UTC end) and the fall-back night (2026-10-25) both return the correct local date, no exception. |
| **M1-T06** | Recovery with `sleep_id` pointing at a stored sleep → that sleep's wake date; recovery with dangling/absent `sleep_id` → local date of `recorded_at`. |
| **M1-T07** | Workout starting 2026-06-10 23:50 local → `2026-06-10` (start-date rule, even though it ends next day); same rule for cycles. |
| **M1-T08** | **Night window.** With a sleep 23:00→07:00 for date D and air readings at 22:30, 23:30, 03:00, 07:30 — the night window for D selects exactly the 23:30 and 03:00 readings. With no sleep for D → `None`. |

## M2 — Derived layer, readiness, baselines, flags

| ID | Test case |
|---|---|
| **M2-T01** | **Golden day rollup.** Fixtures for 2026-06-10: recovery (score 60, hrv 55, rhr 52), night sleep (perf 80, duration 7h), cycle (strain 12.4), one workout, three night air readings (eCO₂ 700/900/800). `run_daily_derivation` produces one `daily_summary` row for the date with each column equal to the hand-computed expected value (assert every populated column explicitly, incl. `night_eco2_ppm_avg == 800.0`, `night_eco2_ppm_max == 900.0`). |
| **M2-T02** | **Idempotency (house invariant).** Run `run_daily_derivation(db, days_back=7)` twice; between runs no source data changes. Assert: identical row counts in `daily_summary`/`baseline`/`insight_card`, identical `daily_summary` values, and primary keys unchanged (rows updated, not re-created). |
| **M2-T03** | **Readiness, all components.** recovery 60, sleep perf 80, clean air (eCO₂ 800, temp 19, humidity 45 → env 100): readiness = 0.5·60 + 0.3·80 + 0.2·100 = **74.0**; `readiness_components` JSON lists all three with their weights. |
| **M2-T04** | **Renormalization on missing air.** Same but zero air readings: readiness = (0.5·60 + 0.3·80) / 0.8 = **67.5**; `readiness_components` contains no `environment` entry. Use a pre-Mill date to mirror reality. |
| **M2-T05** | **No fake readiness.** Recovery missing → `readiness_score is None`. Recovery present but `user_calibrating=True` → also `None`. |
| **M2-T06** | **Air score penalties.** Parametrize: eCO₂ 1100 → env 75; eCO₂ 1500 → 60; temp 23 °C (in-band CO₂/humidity) → 85; humidity 25 % → 90; all three bad (eCO₂ 1500, temp 23, humidity 25) → 60−15−10 = 35; score clamps at ≥ 0. |
| **M2-T07** | **Baselines.** 40 days of `daily_summary` with known HRV values: 7/30/90-window `baseline` rows have hand-computed mean/SD/n; baselines exclude the newest (today's) row; z-score is `None` when n < 14 or SD == 0. |
| **M2-T08** | **Flag thresholds are exact.** Synthetic 30-day HRV series (mean 55, SD 5): today HRV 47.5 (z = −1.5) → `hrv_drop` fires; 48.0 (z = −1.4) → does not. Same boundary discipline for `rhr_elevated` (+1.5) and `sleep_debt` (7d mean at 89 % vs 91 % of 90d mean). |
| **M2-T09** | **Illness warning is a conjunction.** Exactly one of {hrv_drop, rhr_elevated, resp_rate_up, skin_temp_up} firing → no `illness_warning` card; two firing → card upserted with `kind="illness_warning"` and it appears in `daily_summary.flags`. |
| **M2-T10** | **Catch-up self-heals.** Newest `daily_summary` is 3 days stale; the startup catch-up path triggers a derivation that fills all missing dates through yesterday. Also: `POST /derived/run?days_back=3` returns per-step counts and fills the same gap. |
| **M2-T11** | **Provenance.** Every derived row has `source == "derived"` and `source_external_id == date.isoformat()`; writing goes through `upsert()` (assert by re-running and checking no duplicate under the unique constraint). |

## M3 — Manual + weather sources, reserved tables

| ID | Test case |
|---|---|
| **M3-T01** | **Check-in upserts by date.** `POST /log/checkin {mood:4, energy:3, alcohol_units:1.0}` → 200, one `checkin_daily` row with `source_external_id == "checkin:<today>"`. Second POST same date with `{mood:2}` → still exactly one row, `mood == 2`, other fields per upsert semantics. `?date=2026-06-01` writes to that date. |
| **M3-T02** | **Check-in validation.** `mood: 0` and `mood: 6` → 422; negative `alcohol_units` → 422; empty body → 200 (all fields optional, row still keyed to the date). |
| **M3-T03** | **Intake idempotency by client UUID.** Two `POST /log/intake` with the same `client_id` UUID → one `intake_event` row; different UUIDs → two rows. Missing `client_id` → 422. |
| **M3-T04** | **Weather adapter parses without network.** Mock the Open-Meteo response (checked-in JSON fixture with **fabricated placeholder values**, real API *shape*) for a 3-day range → 3 `weather_daily` rows with correct `temp_min_c`/`temp_max_c`/`daylight_seconds`; a malformed/partial payload skips the bad day with a `SyncResult.notes` entry, no exception. Assert `httpx` was called with `home_lat`/`home_lon` from `Settings`. |
| **M3-T05** | **Weather disabled at default coords.** With `home_lat == home_lon == 0.0`, `sync_incremental()` returns an empty `SyncResult` and performs zero HTTP calls (assert mock not called). |
| **M3-T06** | **Weather cursor.** After a sync through date D, the next `sync_incremental()` requests only dates > D (inspect mocked request params) and advances the cursor. |
| **M3-T07** | **Reserved tables exist.** `biomarker` and `nutrition_entry` are in the metadata and the Alembic-migrated DB, each with the `(source, source_external_id)` unique constraint; inserting a duplicate key raises `IntegrityError`. No routes exist for them (`/log/biomarker` → 404). |
| **M3-T08** | **Manual source honors the seam.** `get_source("manual", db)` resolves; `capabilities() == {"checkin", "intake"}`; `backfill()`/`sync_incremental()` return empty `SyncResult`s with zero counts and touch no tables. |
| **M3-T09** | **Auth extension.** M0-T04's parametrized auth test now covers `/log/*` (extend, per M0-T04 note). |

## M4 — Correlation engine + training load

| ID | Test case |
|---|---|
| **M4-T01** | **Planted correlation is found.** Synthetic 90 days of `daily_summary`: `alcohol_units ∈ {0,1,2}` random; next-day HRV = 55 − 6·units + N(0, 2) (seeded RNG). Engine publishes a card for (alcohol → HRV, lag 1) with negative effect, `n ≥ 30`, and gate-passing stats; the natural-units phrasing (median-split difference) has the correct sign. |
| **M4-T02** | **Null data publishes nothing.** 90 days where all inputs and outcomes are independent seeded noise → **zero** published cards. Run with 3 different seeds. |
| **M4-T03** | **Benjamini–Hochberg unit test.** For p-values `[0.001, 0.008, 0.039, 0.041, 0.042, 0.06, 0.3, 0.9]` at q = 0.05, exactly the first **5** survive (BH: largest k with p(k) ≤ k·q/m = 5). Pure-function test on the FDR helper. |
| **M4-T04** | **Gates are hard.** A pair with n = 29 (ρ = 0.9) → not published; n = 30 → eligible. A pair with |ρ| = 0.24 and p ≪ 0.05 → not published. |
| **M4-T05** | **Card lifecycle is deterministic.** Re-running on unchanged data updates the existing card in place (same `source_external_id`, e.g. `"corr:alcohol_units:hrv_rmssd_ms:lag1"`, row count stable). Re-running after replacing the data with null noise flips the card to `status="expired"` — it is not deleted. |
| **M4-T06** | **Training-load bands.** 28 days of cycle strain fixtures: (a) 7d mean 13.0 / 28d mean 8.0 (ratio 1.63) → `training_load` card with caution copy; (b) ratio 1.0 → card reports "ok", no caution; (c) < 14 days of data → no card. Boundary: ratio exactly 1.5 → no caution (rule is > 1.5). |

## M5 — LLM seam, brief, ask

All tests use `FakeProvider(LLMProvider)` (records calls, returns canned text). The real
`ClaudeProvider` is never constructed in tests (assert via monkeypatched constructor or
provider registry).

| ID | Test case |
|---|---|
| **M5-T01** | **Key-less degradation.** With `anthropic_api_key == ""`: `GET /insights/brief` → 503 with a clear JSON message; `POST /insights/ask` → 503; every non-LLM route (today, trends, log, derived) unaffected. |
| **M5-T02** | **Privacy whitelist (invariant).** Populate the DB with a `Profile` (email `"x@example.com"`, fabricated), a `WhoopConnection` (token `"tok-secret"`), and canonical rows with distinctive `raw` payload markers. `build_feature_context(db, days=90)` output, serialized to JSON, contains **none of**: the email, name, token value, any key named `raw`/`access_token`/`refresh_token`/`email`/`first_name`/`last_name` (recursive walk), nor the raw-payload marker strings. This test is the enforcement of TECH_SPEC §10's privacy contract — treat a failure as a release blocker. |
| **M5-T03** | **Brief caching.** Two `GET /insights/brief` on the same date → FakeProvider called exactly once, same text returned; `?refresh=true` → called again, cache row replaced; new date → new call. Cached row stores `model` and `created_at`. |
| **M5-T04** | **Token cap.** With `llm_daily_token_cap = 100` and FakeProvider reporting >100 tokens used today: next LLM call is refused (429 or 503 with a "cap" message), non-LLM routes unaffected; cap resets for a new date. |
| **M5-T05** | **Seam substitution.** `llm_provider = "fake"` (test registry entry) routes brief + ask through FakeProvider; the prompt passed to it contains readiness + flags features (spot-check keys) — proving both features consume `build_feature_context` rather than building their own prompts. |
| **M5-T06** | **Ask is single-turn and grounded.** `POST /insights/ask {"question": "how was my sleep?"}` passes the question and 90-day feature context to the provider; a second ask shares no state with the first (FakeProvider sees no conversation history). Empty question → 422. |

## M6 — PWA dashboard

| ID | Test case |
|---|---|
| **M6-T01** | **Pages render from a populated store.** With two weeks of fixture summaries: `GET /`, `/trends`, `/day/2026-06-10`, `/log` → 200 `text/html`; the Today page body contains the readiness score value and each active card title; `/day/<no-data-date>` → 200 with an explicit empty state, not a 500. |
| **M6-T02** | **Installable + self-contained.** `GET /static/manifest.json` and the service-worker JS → 200; rendered templates reference **no external origins** (regex over the HTML for `https?://` allowing only same-origin/relative URLs — enforces the vendored-assets rule); all referenced static assets exist on disk. |
| **M6-T03** | **Log round-trip.** POST the daily-log form (htmx endpoint) → `POST /derived/run` → `GET /dashboard/today` includes the submitted mood/alcohol values in the summary payload — proving form → canonical → derived → UI end-to-end. |
| **M6-T04** | **JSON API contracts.** `GET /dashboard/today`, `/dashboard/trends?metrics=hrv_rmssd_ms&days=90`, `/dashboard/day/{date}`, `/dashboard/cards` each return 200 with the §11 shape (assert required keys); unknown metric name → 422; malformed date → 422. |
| **M6-T05** | **Auth + no-cache of health data.** M0-T04's parametrized auth test covers the page routes and `/dashboard/*`; the service worker source does not cache `/dashboard`, `/insights`, or `/log` paths (static shell only — assert on the SW file's route list). |

---

## Coverage summary

| Milestone | Cases | Invariants guarded |
|---|---|---|
| M0 | 5 | migrations replay · safe defaults · auth wall |
| M1 | 8 | day/timezone correctness (the rollup foundation) |
| M2 | 11 | idempotent derivation · explainable readiness · exact thresholds |
| M3 | 9 | upsert-by-key for manual input · no-network adapters · schema reservations |
| M4 | 6 | no spurious insights (FDR + gates) · deterministic cards |
| M5 | 6 | **privacy whitelist** · key-less operation · cost cap · seam substitutability |
| M6 | 5 | end-to-end round-trip · self-contained PWA · auth everywhere |

50 cases total. M2-T02, M3-T01/T03, M4-T05 and M5-T02 are the direct heirs of the repo's
two house invariants (idempotency, secrets/PII containment) — if you only run five tests
before merging, run those.
