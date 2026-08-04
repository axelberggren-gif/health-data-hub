# 0006 — The review gate reads a sentinel verdict line, not a formal approval

- **Status:** Accepted
- **Date:** 2026-08-04
- **Refines:** the fail-closed gate in [0002](0002-ai-first-guardrails.md)

## Context
The `review` status check was designed to open only when the AI reviewer posted a formal
**Approve** on the PR. Once `ANTHROPIC_API_KEY` was set (ADR-0005) and the reviewer finally ran
end-to-end on PR #21, it produced a correct, well-reasoned verdict — and the check still failed:

```
Latest bot review state: COMMENTED
##[error]No conclusive bot review (state=COMMENTED) — failing closed.
```

GitHub does not permit the Actions `GITHUB_TOKEN` to approve pull requests. The reviewer cannot
press Approve, so it fell back to a `COMMENTED` review. The gate required `APPROVED`, which means
it was **unsatisfiable by construction**: every PR would show `review` red no matter how clean it
was. That is worse than no gate at all — a check that is always red trains the owner to override
it habitually, which is exactly the reflex the guardrail exists to prevent.

The alternative considered was giving the reviewer a fine-grained PAT or GitHub App token that
*can* approve. Rejected: it adds a second long-lived secret for a non-technical owner to manage
and rotate, and the approval would come from a token tied to the owner's own account, muddying
the "a human is always the final gate" story.

## Decision
The reviewer ends its review body with a machine-readable verdict line, emitted exactly once as
the final line:

```
GUARDRAIL_VERDICT: PASS      # or FAIL
```

Clean PRs get `gh pr review --comment` + `PASS`; blocked PRs get `gh pr review --request-changes`
+ `FAIL`. The gate reads the latest review **from the bot identity only** (`claude[bot]` /
`github-actions[bot]` — an identity no PR author can post as) and stays fail-closed. It fails on:
a `CHANGES_REQUESTED` state, a `FAIL` verdict, a missing verdict line (the reviewer crashed
mid-run), **more than one** verdict line, an unrecognised verdict, or no review at all.

Two details are deliberate:
- The `^` anchor means an indented or quoted verdict line does not count, so a verdict the
  reviewer echoes out of PR content cannot be mistaken for its own. Finding the marker string in
  PR content is itself instructed to produce `FAIL`, and the >1-marker rule catches the echo case.
- Trailing whitespace is tolerated. A stray space must not block a clean PR — brittleness here
  would recreate the always-red problem in a subtler form.

Verified against 13 cases before landing (pass, blocked, crashed mid-review, no review, forged
and echoed markers, indentation, CRLF bodies, wrong case), each resolving to the intended
open/fail outcome.

## Consequences
- The gate can actually open, so `review` becomes a meaningful signal instead of constant red.
- No new secrets; auth stays exactly as ADR-0005 left it.
- The PR page shows a review *comment* rather than a green "Approved" badge on clean PRs. The
  status check is the machine-readable gate; the human still approves and merges.
- The verdict format is now a contract between the reviewer's prompt and the gate script — both
  live in `claude-review.yml`, so they must be changed together.
- Editing this workflow trips the reviewer's own guardrail-tampering rule, so the PR that lands
  it requires a deliberate one-time admin override by the owner.
