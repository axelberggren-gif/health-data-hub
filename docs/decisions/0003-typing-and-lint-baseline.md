# 0003 — Pragmatic typing & lint baseline

- **Status:** Accepted
- **Date:** 2026-06-23

## Context
The codebase had no prior type-checking or lint history when CI was introduced. Source adapters
(`app/sources/*`) parse untyped JSON from third-party APIs, which makes a strict `mypy`
configuration noisy with errors unrelated to any given change — unworkable as a required check
for a non-technical owner.

## Decision
Start `ruff` + `mypy` from a **green, pragmatic baseline** rather than maximal strictness:
- `ruff`: a sensible rule set (`E,W,F,I,UP,B,C4`); the existing code was auto-formatted and
  safe-fixed to conform.
- `mypy`: `ignore_missing_imports`, `check_untyped_defs=false`, with `app.sources.*` kept lenient.
  A few precise `# type: ignore[...]` comments cover known SQLAlchemy/ABC dynamic-attribute
  limitations (kept local, not blanket module ignores).
- All four checks (`ruff check`, `ruff format --check`, `mypy app`, `pytest`) are green and
  required in CI.

## Consequences
- CI is green and meaningful from day one without drowning the owner in pre-existing-type noise.
- Strictness can be tightened incrementally (e.g. enable `disallow_untyped_defs` per module as
  types firm up) — each tightening is a normal PR.
