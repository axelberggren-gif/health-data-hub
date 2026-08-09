# 0009 — A new package's first `CLAUDE.md` blocks the review gate

- **Status:** Proposed — the decision in "Options" is the owner's to make
- **Date:** 2026-08-09

## Context

ADR-0007 gave the `claude-review` bot one carve-out: an AI agent may self-certify a
`CLAUDE.md` edit **only** when every hunk falls under that file's `## Recent changes`
heading. Its stated reasoning was that `AGENTS.md` *requires* every PR to update that list,
so blocking it "would make every ordinary PR unmergeable — the rule would eat itself".

Milestone M1 (PR #26) hit the same self-eating problem through a different mandated edit.
The bot found no code defects, and still returned `GUARDRAIL_VERDICT: FAIL` on two hunks:

1. `app/CLAUDE.md` — adding `derived/` to the **Key files** sub-package list.
2. `app/derived/CLAUDE.md` — a new per-directory canon file, which necessarily has
   Purpose / Key files / Conventions / Invariants sections.

Both are required by rules already in the repo, so neither can simply be dropped:

- `TECH_SPEC_V1.md:89` — "Each new package gets its own `CLAUDE.md` … **in the PR that
  creates it**."
- Every `CLAUDE.md` header — "If reality and this file disagree, **fix this file in the same
  PR**." Leaving `derived/` out of the sub-package list would knowingly commit stale canon.

So the rule eats itself again: **any milestone that adds a package fails `review` by
construction**, and `review` is a required check under branch protection. V1 has four more
package-adding milestones — M3 (`app/sources/manual/`, `app/sources/weather/`), M4 and M5
(`app/insights/`), M6 (`web/`) — so this recurs at least four more times.

Note what is *not* wrong here: the bot applied rule 4 correctly, and its instinct is sound.
An agent that writes its own safety rules and then certifies them is exactly the failure this
machinery exists to prevent. The problem is that the carve-out is narrower than the set of
`CLAUDE.md` edits the project itself mandates.

## Options

**A — Widen the carve-out (recommended).** Amend rule 4 in
`.github/workflows/claude-review.yml` so two more cases don't block: (i) a **brand-new**
per-directory `CLAUDE.md` added by the same PR that creates its directory, and (ii) adding or
removing an entry in an existing file's Key-files/sub-package *list*. Editing the rule
*sections* of an **existing** `CLAUDE.md` keeps blocking — that is the case genuinely worth a
human, because it rewrites rules already in force.

The security argument for (i) is that a new directory's `CLAUDE.md` adds no *loosening*: it
constrains code that did not exist before this PR, and the bot still reviews the code itself
against the global invariants in `AGENTS.md`. The risk it does carry is an agent writing a
weak invariant for its own new package — which the owner sees in the normal diff, since the
file is new and therefore reads as an addition, not a subtle edit.

**B — Override per milestone.** Change nothing; the owner reads the hunks and uses the
`ONBOARDING.md` admin override each time a milestone adds a package, adding a note here per
override. Maximum strictness, recurring manual cost, and it trains the owner to reach for the
override — which is the outcome the break-glass section warns against.

**C — Defer the docs.** Ship the package without its `CLAUDE.md`, then add the docs in a
separate PR. Makes `review` pass unaided, but violates `TECH_SPEC_V1.md:89` and leaves a
window where a package has no canon — precisely when the next agent is most likely to read it.

## Decision

Not yet taken — recorded as Proposed so the conflict is documented rather than rediscovered at
M3. **M1 (PR #26) proceeds under option B**: the owner reads the two hunks and merges. Whether
the carve-out is widened for M3 onward is the owner's call.

Deliberately not done in PR #26: an agent must not edit `.github/` to make its own PR pass.
Any change under option A belongs in its own PR, reviewed closely, and will itself be blocked
by rule 4 — as it should be, since that PR really does loosen the guardrails.

## Consequences

- Until this is settled, every package-adding milestone costs one owner override. That is
  visible and safe, but it is friction on the critical path of V1.
- If option A is taken, the guardrail gets *narrower in scope but sharper*: it stops crying
  wolf on mandated documentation, so a future block on an existing file's Invariants section
  carries real signal instead of being the fourth false alarm the owner has waved through.
- Revisit if the reverse failure ever appears — an agent shipping a new package whose
  `CLAUDE.md` quietly grants itself permissions the global invariants deny. Option A's
  scope-limit (new directories only, no edits to existing rules) is what keeps that bounded.
