# 0004 — Pin claude-code-action to a known-good commit, not the moving `v1` tag

- **Status:** Accepted
- **Date:** 2026-06-23

## Context
The `claude-review` workflow uses `anthropics/claude-code-action`. Initial setup SHA-pinned it to
whatever `v1` resolved to that day — commit `30544b67` (released 2026-06-22). That version
**rejected the OAuth subscription token immediately** (`is_error` on turn 1, $0 cost, no review
posted), so the `review` gate failed closed and every PR was blocked. The sibling repo
`3-musketeers-wc-game` runs the same action + the same `CLAUDE_CODE_OAUTH_TOKEN` mechanism
successfully — but pinned to the older commit `70a6e525` (2026-06-03). So the failure was a
**regression in the newer action release**, not the account, plan, or token.

## Decision
Pin `claude-code-action` to the known-good commit `70a6e5256e9e2366a1ed5c041904a982ba3a328f`
(the 2026-06-03 `v1`) rather than tracking the moving `v1` tag. This is the intended benefit of
SHA-pinning: a third-party regression can't silently break the gate.

## Consequences
- The reviewer authenticates reliably with the existing `CLAUDE_CODE_OAUTH_TOKEN` (no API key needed).
- Dependabot's `github-actions` updates will propose newer commits as reviewable PRs; bump only
  after confirming the new release works (re-run a PR's `review` check on the bump PR).
- If the reviewer breaks again after a bump, revert to this commit.
