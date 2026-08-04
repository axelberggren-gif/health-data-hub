# 0007 — Reviewer carve-outs: `CLAUDE.md` "Recent changes", and Dependabot PRs

- **Status:** Accepted
- **Date:** 2026-08-04
- **Refines:** the guardrail-tampering rule and the gate's author check from
  [0002](0002-ai-first-guardrails.md) / [0006](0006-gate-reads-a-sentinel-verdict-line.md)

## Context
Once the reviewer actually started running (ADR-0005, ADR-0006), two rules that had never been
exercised turned out to block ordinary work.

**1. The `CLAUDE.md` rule ate itself.** The reviewer blocks any diff touching a `CLAUDE.md`, on
the reasonable grounds that those files *are* the rules. But `AGENTS.md` separately **requires**
every PR to update the "Recent changes" list of any directory it touches. Every substantive PR
therefore had two options: skip a mandated step, or be auto-blocked. Two guardrails pointed in
opposite directions, and the contradiction only surfaced because the reviewer finally worked.

**2. Dependabot PRs can never pass, for a reason no repo setting can change.** GitHub treats a
Dependabot `pull_request` like a fork PR: the workflow receives a **read-only `GITHUB_TOKEN`** and
**no access to Actions secrets** — only Dependabot secrets are exposed. So on those PRs the
reviewer has no `ANTHROPIC_API_KEY`, and even with one it could not post a review, because posting
requires a writable token. Allow-listing `dependabot[bot]` in the gate's author check — the
obvious-looking fix — therefore fixes nothing; it just moves the failure later.

The documented escapes are to store the key as a Dependabot secret (doesn't help: the token is
still read-only) or to re-trigger via `pull_request_target`. The latter would work, and it is
rejected: `pull_request_target` runs with full secrets in the context of a PR branch, which is
precisely the exposure ADR-0002 chose `pull_request` to avoid. Trading the repo's central security
property for automated review of version bumps is a bad trade on a public repo.

## Decision

**`CLAUDE.md`:** the reviewer does not block a `CLAUDE.md` edit whose hunks fall only under that
file's `## Recent changes` heading. Any edit to Purpose, Key files, Conventions, or Invariants
still blocks. `AGENTS.md`, `.github/`, `.claude/` and `.gitignore` continue to block in full.
`AGENTS.md` step 3 now states the carve-out so agents know the mandated update is allowed.

**Dependabot:** accept that `review` is always red on Dependabot PRs, and make the gate *say so
usefully*. It now detects `github.actor == 'dependabot[bot]'` and fails with a message naming the
platform limitation and the actual next step, instead of the misleading "Untrusted author
(CONTRIBUTOR)". `build` and `lint` still run on those PRs and remain the real signal —
particularly `build`, which proves the test suite passes against the new version. `ONBOARDING.md`
gains a short runbook so the weekly red check is expected rather than alarming.

## Consequences
- Ordinary PRs can follow every rule in `AGENTS.md` and still go green — the common case works.
- The parts of a `CLAUDE.md` that carry actual rules keep human review; only the changelog-ish
  list is exempt. The reviewer judges this from the diff, so a PR that sneaks a rule change into a
  "Recent changes" hunk is still caught.
- Dependency bumps need a deliberate human merge each week. That is a real cost in owner
  attention, and the deliberate upside is that supply-chain changes — the highest-risk category
  in this repo — are never merged unread.
- The security model from ADR-0002 is unchanged: still `pull_request`, still no secrets exposed to
  PR-controlled code.
- If Dependabot review ever becomes worth automating, the path is a separate `workflow_run`-based
  job, not `pull_request_target`. Revisit only with a written threat model.
