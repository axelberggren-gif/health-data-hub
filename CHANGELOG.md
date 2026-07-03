# Changelog

All notable changes to this project. Newest first. One short line per change, added in the same
PR that makes the change.

## Unreleased

### Added
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

### Changed
- Formatted the codebase with `ruff` and added exception chaining (`raise ... from exc`) in API routes.

- Pinned `claude-code-action` to a known-good commit (reviewer auth fix).
