> **Canon** — current source of truth for any AI agent working in this repo. If reality and
> this file disagree, fix this file in the same PR.

# Health Data Hub — root brief for AI agents

This is the canonical entry point for any AI coding agent (Claude Code, Codex, Cursor, Aider,
Copilot, …) working in this repo. Claude Code loads it via the `@AGENTS.md` import in
`CLAUDE.md`. Other agents should read it directly.

The owner (Axel) is **non-technical**. The guardrails in this repo exist so that AI agents can
do the work while the *important technical decisions are recorded and automatically enforced*.
Respect them strictly — they are not optional style preferences.

## Project at a glance

- **Stack**: Python 3.12+ · FastAPI · SQLAlchemy 2.0 (typed `Mapped[...]`) · Pydantic v2 /
  pydantic-settings · httpx. SQLite by default (`health.db`); Postgres via `DATABASE_URL`.
- **Purpose**: pull personal health data from **WHOOP** (official OAuth2 v2 API) and
  **Mill Sense** (indoor air quality) into a **source-agnostic canonical store**, and export it
  as JSON/CSV — the foundation for a personal health "super-app" (aggregation + insights; see
  `SUPER_APP_PLAN.md`). More sources (Apple HealthKit, Oura, Garmin) plug in without reworking
  the core.
- **Lifecycle**: a personal project, public source code, **no personal data ever committed**.

## Session-start ritual (every session, in order)

1. Read this file (Claude Code auto-loads it via `CLAUDE.md`).
2. `tail -n 40 CHANGELOG.md` — what changed recently.
3. `git log --oneline -10 && git status` — what's in flight.
4. Read `docs/decisions/` (the ADR log) for accepted technical decisions you must honour.
5. Read the per-directory `CLAUDE.md` for the area you'll touch (map below).
6. Verify git identity: `git config user.name` must be a **human name**, not "Claude". If
   wrong, ask the human to fix it — never set it yourself. **Exception — cloud sessions**
   (Claude Code on the web): the container's git identity is a sandbox default that the
   agent may not change and the human cannot persist. There, accountability comes from the
   GitHub PR author (a human account) plus the `Co-authored-by` trailer — note it in the PR
   and carry on.
7. Read `.claude-identity` (gitignored) for the human's initials, used in branch names and
   CHANGELOG attribution. If missing, ask the human to copy `.claude-identity.example`. In
   cloud sessions the file is never present — it is gitignored, so it is never cloned — so
   fall back to the initials used in recent `CHANGELOG.md` entries and say which you used.

## Per-directory CLAUDE.md map

@app/CLAUDE.md
@app/sources/CLAUDE.md
@app/sync/CLAUDE.md
@app/api/CLAUDE.md
@app/export/CLAUDE.md
@tests/CLAUDE.md

## Global invariants (do NOT break — the `claude-review` bot blocks PRs that violate these)

1. **Source seam.** Every data source subclasses `HealthDataSource` (`app/sources/base.py`) and
   implements `capabilities()`, `backfill()`, `sync_incremental()` (plus `authorize_url()` /
   `handle_webhook()` where relevant). A source maps its native payload → canonical models and
   must **not** import from `app.sync`, `app.export`, or open DB sessions itself. New sources
   register in `app/sources/registry.py`.
2. **Idempotent persistence.** All writes to canonical tables go through
   `app.sync.orchestrator.upsert()`, keyed on `(source, source_external_id)`. Never raw-insert a
   record that a re-sync could duplicate. Track incremental progress with
   `get_cursor` / `set_cursor`. Each canonical table has a matching
   `UniqueConstraint("source", "source_external_id")`.
3. **Canonical model is the contract.** `app/models.py` is the single shape consumers
   (export, future analytics/insights) read. Don't leak a source's native payload shape
   downstream; map it into the canonical model first.
4. **Secrets only via config.** All secrets/config come from `Settings` (`app/config.py`) which
   reads environment / `.env`. Never hard-code a client secret, password, token, or API key.
   `.env`, `*.db`, `exports/`, and generated charts are **never** committed (see Secrets below).
5. **OAuth safety.** Any OAuth callback validates the CSRF `state`. Access/refresh tokens are
   **never written to logs** or returned in API responses beyond what's strictly needed.

## Workflow

### Branches
`<type>/<initials>/<short-kebab>` where `<type>` ∈ `feat fix chore docs refactor perf ci test`.
Examples: `feat/ax/oura-source`, `fix/ax/mill-poll-window`. Get initials from `.claude-identity`.
Branch off `main`; never commit directly to `main`.

### Commits & PR titles
[Conventional Commits](https://www.conventionalcommits.org). The PR title becomes the squash
commit on `main`, so it must be valid (enforced by `pr-title-lint`). Examples:
`feat(sources): add Oura adapter`, `fix(sync): handle empty cursor`.
Every commit you author ends with the trailer:
`Co-authored-by: Claude <noreply@anthropic.com>` (or your agent's trailer).

### Pull requests (the only path to `main`)
1. Push your branch; open a PR against `main`; fill in the template.
2. Update `CHANGELOG.md` (newest first) in the same PR.
3. If you touched a directory with a `CLAUDE.md`, update its "Recent changes" list. This is
   the one edit to a `CLAUDE.md` the reviewer does **not** block — see the carve-out in its
   guardrail-tampering rule. Changing any *other* section of a `CLAUDE.md` (Purpose, Key
   files, Conventions, Invariants) still needs the owner's manual review, because those are
   the rules themselves.
4. If you changed an **architectural seam** (`app/sources/base.py`, `app/models.py`,
   `app/sync/orchestrator.py`), add an ADR in `docs/decisions/` (see its README).
5. Three checks must pass. The names on the PR page are the **job** names, not the workflow
   names: **`build`** (the `ci` workflow — lint/format/type/test), **`review`** (the
   `claude-review` workflow — the AI gate), **`lint`** (the `pr-title-lint` workflow). Those
   three job names are what branch protection requires. Then **Axel presses Merge** — the bot
   reviews and can block, but a human is always the final gate. Squash-merge only.

### Task tracking
GitHub Issues + a Project board. File via the issue forms in `.github/ISSUE_TEMPLATE/`. Reference
issues in **PR descriptions / commit trailers only** (`Closes #N` / `Refs #N`) — never in source
code or `CLAUDE.md`, so the codebase stays tracker-agnostic. Labels live in `.github/labels.yml`.

## Required commands (`make help` lists them)
- `make dev` — run the API locally (`uvicorn`, port 8000).
- `make check` — the full verify loop CI runs: `ruff check` + `ruff format --check` + `mypy app`
  + `pytest`. **Run this before opening a PR; "green locally" == "green in CI".**
- `make test` / `make lint` / `make format` / `make typecheck` — the individual steps.
- `make audit` — scan dependencies for known vulnerabilities (`pip-audit`).

## Environment variables
See `.env.example` for the full set. Runtime: `DATABASE_URL` (optional; defaults to SQLite),
`WHOOP_CLIENT_ID`, `WHOOP_CLIENT_SECRET`, `WHOOP_REDIRECT_URI`, and (for air quality)
`MILL_USERNAME`, `MILL_PASSWORD`. All are read via `app/config.py` (`Settings`). Defaults are
safe placeholders so the app boots without credentials.

## Secrets & personal data (this repo is PUBLIC — read carefully)
- **Never** add a real secret or any personal/health data to a tracked file — including code,
  tests, fixtures, docs, committed databases, charts, or CSV/JSON exports. Placeholders in
  `.env.example` are the only credentials that belong in git.
- The real `.env` and `health.db` stay local and are `.gitignore`d. Generated charts
  (`*.png`, `*.html`) are ignored by default; opt in individually with `git add -f` only after
  confirming a file contains no personal data.
- If you ever suspect a secret was committed, stop and tell the owner — it must be rotated.

## Emergency / break-glass (for the owner)
`main` is branch-protected; the automated path never merges unreviewed code. If a required check
is wrong or stuck and you must merge anyway, that is a deliberate, rare admin override (the repo
is configured so the owner *can* override, but shouldn't routinely). See `ONBOARDING.md` →
"Emergency: merging anyway". After any override, add a short ADR noting why.
