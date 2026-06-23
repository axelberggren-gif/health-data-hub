# 0005 — AI reviewer authenticates with an Anthropic API key

- **Status:** Accepted
- **Date:** 2026-06-23
- **Supersedes:** the OAuth-token auth in [0002](0002-ai-first-guardrails.md)

## Context
The plan was for `claude-review` to authenticate with a `claude setup-token` OAuth token tied to a
Claude subscription (as the sibling `3-musketeers-wc-game` repo does successfully). In practice the
account is on a Claude **Team** plan: freshly-minted `setup-token` tokens are rejected by the API
(`is_error` on turn 1, ~2s, $0), and the one token that *does* work lives only inside the sibling
repo's secret — which GitHub will not reveal (secrets are write-only). This was verified
exhaustively: PR #9 ran the *exact* action commit that works in 3-musketeers (`70a6e525`) with a
freshly-set token and still failed instantly, while a re-run of 3-musketeers' own reviewer
succeeded the same day. So the failing variable is the token value, and it can't be fixed on the
OAuth path here.

## Decision
Authenticate the reviewer with a pay-per-use **Anthropic API key** (`ANTHROPIC_API_KEY` secret,
from console.anthropic.com): the workflow uses `anthropic_api_key:` instead of
`claude_code_oauth_token:`. The action stays SHA-pinned to the known-good `70a6e525` (ADR-0004).

## Consequences
- Reliable auth, independent of the claude.ai plan.
- Small metered cost (a few cents per PR review) on the Anthropic API account; set a monthly budget.
- Everything else (fail-closed gate, least-privilege, SHA-pinning, the merge model) is unchanged.
- If the account later has an individual Pro/Max subscription, it could switch back to a
  subscription token — but the API key is the durable default.
