# Security policy

This is a personal project that handles **health data** and OAuth credentials, so it
takes secrets seriously even though the source code is public.

## Reporting a vulnerability

Please **do not open a public issue** for a security problem. Instead, use GitHub's
private vulnerability reporting: the **Security → Report a vulnerability** button on this
repo. The maintainer will respond as soon as possible.

## What is and isn't in this repo

- **Never committed:** the real `.env` (WHOOP client secret, Mill password), the local
  `health.db` (your biometrics), and any exports or personal charts. These are
  `.gitignore`d and protected by GitHub secret-scanning push protection.
- **In the repo:** integration source code, the canonical data model, and the CI/review
  pipeline. No personal data lives here.

## Security model (how the guardrails protect main)

- All changes go through a pull request; nobody pushes to `main` directly.
- CI (`ci`), the AI reviewer (`claude-review`), and PR-title lint (`pr-title-lint`) must all
  pass before a PR can be merged. The AI reviewer **fails closed** — if it can't run or
  isn't conclusive, the merge is blocked.
- Workflows trigger on `pull_request` (never `pull_request_target`), so **pull requests from
  forks run with a read-only token and no secrets** — the maintainer's Claude token is never
  exposed to untrusted code. Fork PRs are reviewed manually by the maintainer, not the bot.
- Third-party GitHub Actions are pinned to specific commit SHAs to prevent supply-chain
  tampering; Dependabot proposes updates as reviewable PRs.

## If a secret is ever leaked

Assume any secret that reaches a public commit is compromised — **rotate it immediately**
(re-issue the WHOOP client secret, change the Mill password) even after deleting the file,
because git history and bots retain it.
