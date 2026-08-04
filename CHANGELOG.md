# Changelog

All notable changes to this project. Newest first. One short line per change, added in the same
PR that makes the change.

## Unreleased

### Added
- ADR-0009: record of the admin override used to merge M0 — the `review` check failed only
  because the PR edited `.github/workflows/ci.yml`, which the reviewer may never self-approve
  (ax).
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
