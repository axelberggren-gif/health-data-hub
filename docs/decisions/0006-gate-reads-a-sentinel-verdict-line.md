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
+ `FAIL`. The gate considers only reviews that are **from the bot identity** (`claude[bot]` /
`github-actions[bot]` — an identity no PR author can post as) **and submitted against the current
head commit**, then reads the newest of those that carries a verdict line. It stays fail-closed:
it fails on a `CHANGES_REQUESTED` state, a `FAIL` verdict, no verdict line on this commit (the
reviewer crashed mid-run), **more than one** verdict line in the chosen body, an unrecognised
verdict, or no review for this commit at all.

Scoping to the head commit is load-bearing in both directions. Without it a stale `PASS` from an
earlier commit would open the gate if the reviewer later crashed before posting — the gate would
fail *open* on unreviewed code — and an old `CHANGES_REQUESTED` would keep blocking a PR forever
after the problem was fixed.

Taking the newest verdict-**carrying** review rather than simply the newest review matters because
the action posts inline comments as a separate, empty-bodied review. If that lands after the
verdict review, "newest" is a body with no verdict, and a clean PR would be blocked. This was
observed live on PR #21, where the two reviews arrived 14 seconds apart.

Two further details are deliberate:
- The `^` anchor means an indented or quoted verdict line does not count, so a verdict the
  reviewer echoes out of PR content cannot be mistaken for its own. Finding the marker string in
  PR content is itself instructed to produce `FAIL`, and the >1-marker rule catches the echo case.
- Trailing whitespace is tolerated. A stray space must not block a clean PR — brittleness here
  would recreate the always-red problem in a subtler form.

Verified against 13 marker-parsing cases (pass, blocked, crashed mid-review, no review, forged and
echoed markers, indentation, CRLF bodies, wrong case, trailing space/tab) plus 10 review-selection
cases built from PR #21's real payloads (stale-commit PASS, once-blocked-then-fixed, inline
container arriving after the verdict, untrusted identity), each resolving to the intended
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
