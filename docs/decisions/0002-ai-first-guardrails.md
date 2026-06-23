# 0002 — AI-first guardrails on a public GitHub repo

- **Status:** Accepted
- **Date:** 2026-06-23

## Context
The repo should be "AI-first": AI agents do the work, but a non-technical owner needs the
important rules to be **enforced automatically**, not just documented. Enforced branch protection
and required status checks are free on **public** repos but cost money on private ones, and the
personal **data** (`health.db`) and **secrets** (`.env`) are never committed regardless of
visibility. A security audit also flagged that fully hands-off auto-merge with an AI as the sole
approver is prompt-injectable (a crafted PR could trick the bot into approving and merge with no
human in the loop).

## Decision
- **Public repository.** Source code is public; personal data and secrets are gitignored and
  protected by GitHub secret-scanning push protection. Strongest free tooling (CodeQL, secret
  scanning, unlimited Actions).
- **Enforcement = required status checks** on `main`: `ci` (lint/format/type/test),
  `claude-review` (AI reviewer, **fail-closed gate**), `pr-title-lint`. No direct pushes to `main`.
- **Merge model: the bot reviews and blocks; the owner presses Merge.** No auto-merge — a human is
  always the final gate, which closes the prompt-injection-to-`main` risk. (A solo owner can't
  "approve" their own PR in GitHub, so the human gate is the Merge click, and required approvals
  are set to 0.)
- **Supply-chain hygiene:** third-party Actions are SHA-pinned; workflows use `pull_request`
  (never `pull_request_target`) and least-privilege `permissions`; the AI reviewer's tool
  allowlist is minimal and it treats PR content as untrusted.

## Consequences
- Strong, enforced guardrails at zero cost; the owner keeps a ~10-second Merge step per PR.
- Source code is publicly visible (operational metadata, not data). Reversible to private later,
  but existing public history stays public.
- The owner should enable 2FA and rotate the WHOOP secret / Mill password once after setup.
