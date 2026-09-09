# Changelog

All notable changes to this project. Newest first. One short line per change, added in the same
PR that makes the change.

## Unreleased

### Added
- V1 milestone **M3**: the two inputs the store was missing — the owner's own log and the
  weather outside (ADR-0011) (ax).
  - **Daily log** (`POST /log/checkin`, `POST /log/intake`, behind the app token): mood,
    energy, stress and soreness on 1–5 scales, alcohol units, the time of the last coffee, a
    free-text note, and supplements/medication with dose. The check-in is keyed to its local
    date, so filling the form again in the evening *corrects* the morning's answer instead of
    logging a second opinion; an intake event is keyed to a UUID the phone generates, so a
    request retried on a dropped connection cannot double-log the same magnesium.
  - **Weather & daylight** (Open-Meteo, no account, no API key): daily min/max temperature,
    precipitation, sunrise, sunset and daylight seconds for the home location. With
    `HOME_LAT`/`HOME_LON` left at their defaults the source is **off** and makes no network
    call at all — Open-Meteo would otherwise happily report the weather in the Gulf of Guinea.
    Deep history and recent days come from its two different endpoints automatically, so a
    six-month backfill is two requests.
  - Both arrive as **ordinary registered sources** (`manual`, `open_meteo`) through the same
    seam and the same idempotent write path as WHOOP and Mill — not as a side door into the
    database.
  - The check-in and the weather now reach `daily_summary`, including a `caffeine_after_14`
    flag derived from the local clock. A check-in on its own is enough to make a day worth
    summarizing; weather on its own is not, so the store cannot fill with weather-only days.
  - `biomarker` and `nutrition_entry` ship **empty** — no writer, no route, no UI. Reserving
    the shape now means adding blood panels or food logging later is a form, not a migration
    against months of live data.
  - New Alembic revision `0003` (purely additive); the five new tables are included in the
    JSON/CSV export.
  - Tests M3-T01 … M3-T09 from the V1 catalog, plus M3-T10/T11 added to it for the rollup
    wiring. Every HTTP call in the weather tests is mocked against a checked-in fixture with
    fabricated values — no network, no real coordinates.
- V1 milestones **M1 + M2**: the derived layer — the app now draws conclusions instead of only
  storing data (ADR-0009) (ax).
  - `app/derived/dates.py` (M1): day attribution. Every derived date is a *local* date in
    `HOME_TIMEZONE`; sleep counts towards the day you wake up, recovery follows its sleep,
    workouts and cycles their start, and air readings the night you slept through. Handles both
    DST transitions.
  - `daily_summary`: one row per local date holding recovery, the night's sleep, strain,
    night-time bedroom air, and (from M3) weather and the daily check-in — the single shape the
    dashboard, insights and the daily brief will read.
  - **Readiness score**: a transparent 0.5·recovery + 0.3·sleep + 0.2·air blend that
    renormalises when a component is missing (so the months before the air sensor existed are
    not penalised), stores the components it used so the number can always be explained, and
    reports nothing rather than guessing when there is no usable recovery score.
  - `baseline`: trailing 7/30/90-day mean and spread per metric, always excluding the day being
    judged, plus z-scores that stay silent under 14 days of history.
  - **Anomaly flags + illness early-warning**: HRV drop, elevated resting HR, raised
    respiratory rate, raised skin temperature, sleep debt and stale-air streaks. Two of the
    four physiological signals on one day raise one deliberately non-diagnostic warning card.
  - `insight_card`: one row per *finding* (not per day), so a signal that keeps firing updates
    its card and one that resolves expires it.
  - The job (`POST /derived/run`, behind the app token) recomputes a window of days, is a no-op
    when run twice, and catches up on startup — a laptop that slept for three days heals
    itself. Also a daily tick at `DERIVED_RUN_HOUR` (default 06:00 local).
  - `sleep_session.sleep_debt_ms` is now canonical (mapped from WHOOP's `sleep_needed`), so the
    derived layer never reads a source payload. Alembic revision `0002` ships all of the above.
  - Tests M1-T01 … M1-T08 and M2-T01 … M2-T11 from the V1 catalog, plus `tests/factories.py`.
- V1 milestone **M0**: database migrations and the auth wall the rest of V1 builds on (ADR-0008)
  (ax).
  - Alembic (`alembic/`, `alembic.ini`, `make migrate` / `make migration m="…"`): revision `0001`
    is the current schema, so the owner's existing database upgrades in place instead of being
    rebuilt. CI replays `alembic upgrade head` on a scratch database, and a test asserts the
    migrated schema equals `Base.metadata` — a model change that forgets its migration turns
    `build` red.
  - `Settings.app_token` + `require_token` (`app/api/deps.py`): a shared bearer/cookie token,
    mounted on the `/export` router. Empty token = disabled, which stays the local-dev default;
    `/health` and `/` remain public.
  - The remaining V1 settings with safe defaults: `home_timezone`, `home_lat`/`home_lon`
    (0.0 ⇒ weather off), `anthropic_api_key` (empty ⇒ LLM routes off), `llm_provider`,
    `llm_model`, `llm_daily_token_cap`; `.env.example` documents all of them.
  - Tests M0-T01 … M0-T05 from the V1 catalog.
- V1 technical specification (`docs/specs/TECH_SPEC_V1.md`) + test-first acceptance catalog
  (`docs/specs/TEST_SPEC_V1.md`): milestones M0–M6 with 50 numbered test cases (ax).
- `SUPER_APP_PLAN.md`: knowledge-layer design — a compounding self-model alongside the metrics
  (Claude-compiled, GraphRAG-retrieved, confidence + provenance), plus the V1 "emit knowledge
  nodes from day one" note and roadmap/scope updates.
- AI-first GitHub pipeline: CI (`ruff` + `mypy` + `pytest`), AI PR reviewer (`claude-review`,
  fail-closed gate), `pr-title-lint`, label sync, Dependabot, issue/PR templates, `CODEOWNERS`,
  `SECURITY.md`.
- Agent canon: `AGENTS.md` + per-directory `CLAUDE.md` files; `docs/decisions/` ADR log;
  `ONBOARDING.md` for the owner; `verifier` subagent.
- Test foundation: smoke test (app boots) + orchestrator idempotency test.
- Project tooling: `pyproject.toml` (ruff/mypy/pytest config), `Makefile`, `requirements-dev.txt`.

### Fixed
- Reviewer carve-out so ordinary PRs can go green: updating a `CLAUDE.md` "Recent changes" list
  (which `AGENTS.md` requires) no longer trips the guardrail-tampering rule; edits to a
  `CLAUDE.md`'s rule sections still need a human (ADR-0007) (ax).
- Dependabot PRs now fail the `review` gate with an explanation of the platform limitation and the
  next step, instead of a misleading "untrusted author" error (ADR-0007) (ax).
- Corrected the required-check names in `AGENTS.md` / `ONBOARDING.md`: the contexts are the job
  names `build` / `review` / `lint`, not the workflow names (ax).
- The `review` gate could never open: it required a formal Approve, which GitHub does not permit
  the Actions token to give. The reviewer now emits a `GUARDRAIL_VERDICT: PASS` / `FAIL` line that
  the gate reads, still fail-closed on anything ambiguous (ADR-0006) (ax).

### Changed
- Made the verify loop reproducible: pinned `ruff` / `mypy` / `pytest` exactly in
  `requirements-dev.txt`, and `make` now invokes tools via `python -m` so the active
  environment's pinned version runs instead of whatever is on `PATH` (ax).
- `EXPORT_MODELS` (`app/models.py`) is annotated `list[type[Base]]` so export's
  `__tablename__` / `__table__` access type-checks under any mypy version (ax).

- Formatted the codebase with `ruff` and added exception chaining (`raise ... from exc`) in API routes.

- Pinned `claude-code-action` to a known-good commit (reviewer auth fix).
