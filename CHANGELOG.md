# Changelog

All notable changes to this project. Newest first. One short line per change, added in the same
PR that makes the change.

## Unreleased

### Added
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
