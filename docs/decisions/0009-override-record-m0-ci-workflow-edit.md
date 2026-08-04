# 0009 — Override record: M0 merged with a red `review` check

- **Status:** Accepted
- **Date:** 2026-08-04

## Context

PR #23 (milestone M0 — Alembic migrations, the V1 settings, and the app-token auth wall)
was merged with the required `review` check failing. `AGENTS.md` and `ONBOARDING.md` say an
admin override is a rare, deliberate act that gets a short ADR afterwards. This is it.

The reviewer did **not** find a defect. Its review said the auth wall, the settings, the
migration and the tests all passed the guardrail checks, and blocked on one thing only:

> The PR modifies a CI workflow file, `.github/workflows/ci.yml`. My rules say I must never
> self-approve a change to the project's own safety machinery — a human has to review those.

That rule (ADR-0002, reviewer rule 4) is working exactly as designed: an AI agent must not
certify a change to the machinery that checks its own work. The hunk in question adds a step
that replays `alembic upgrade head` against a throwaway SQLite file, so a model change that
forgets its migration turns CI red. It adds a check; it removes and weakens nothing.

The owner read that hunk, agreed, and merged.

## Decision

Record the override rather than change any rule. Specifically:

- The reviewer's `.github/` block stays as-is. It cost one manual read of one hunk and it
  bought a guarantee that no agent can quietly loosen its own gate. That trade is correct.
- No retroactive change to PR #23.

## Consequences

- **Expect this again.** Milestones that touch CI will trip the same block: M2 (the derivation
  job may want a scheduled workflow), and any milestone adding a dependency that needs a CI
  step. That is the intended cost, not a defect to engineer around.
- **Agents should say so up front.** A PR whose diff touches `.github/`, `AGENTS.md`,
  `.claude/`, `.gitignore`, or a `CLAUDE.md` outside its "Recent changes" list will fail
  `review` by construction. The PR description must say which file trips the rule and why,
  so the owner knows before opening the checks that a red `review` is expected and what
  exactly he is being asked to sign off on. This one did not, and the owner had to work that
  out from the bot's comment.
- If CI-touching PRs ever become frequent enough that overrides stop feeling rare, the fix is
  a narrower carve-out (e.g. additive-only steps in `ci.yml`) argued in its own ADR — not a
  habit of overriding.
