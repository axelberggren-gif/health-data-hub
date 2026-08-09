# 0010 — Carve out the `CLAUDE.md` documentation the repo itself mandates

- **Status:** Accepted
- **Date:** 2026-08-09

## Context

ADR-0007 gave the `claude-review` bot one carve-out: an AI agent may self-certify a
`CLAUDE.md` edit **only** when every hunk falls under that file's `## Recent changes`
heading. Its reasoning was that `AGENTS.md` *requires* that edit on every PR, so blocking it
"would make every ordinary PR unmergeable — the rule would eat itself".

The same trap has now closed on a second, wider class of edit. PR #25 (V1 milestones M1 + M2,
the derived layer) was reviewed, found clean on the substance — the bot's own words: *"the
actual code in this PR is in good shape … No secrets or personal data … No data-corruption
risk … Invariants respected … No code changes are required from my side"* — and still returned
`GUARDRAIL_VERDICT: FAIL`, on four documentation hunks:

1. `app/derived/CLAUDE.md` — a brand-new per-directory canon file, which necessarily has an
   Invariants section.
2. `app/CLAUDE.md`, `app/api/CLAUDE.md` — the **Key files** list gained the new package.
3. `tests/CLAUDE.md` — Key files / Conventions.
4. `AGENTS.md` — one line registering the new directory in the per-directory map.

None of those could be dropped, because other rules in the repo require them:

- `docs/specs/TECH_SPEC_V1.md` — "Each new package gets its own `CLAUDE.md` … **in the PR that
  creates it**."
- Every `CLAUDE.md` header — "If reality and this file disagree, **fix this file in the same
  PR**." Omitting the new package from the Key-files list would knowingly commit stale canon.

So the rule ate itself again, and the owner merged #25 by admin override three minutes after
the block. That is one override already spent on documentation the project mandates, and V1 has
four more package-adding milestones queued — M3 (`app/sources/manual/`,
`app/sources/weather/`), M4 and M5 (`app/insights/`), M6 (`web/`). Left alone, this guarantees
at least four more overrides for the same non-reason, which is exactly the habit the
break-glass section of `ONBOARDING.md` warns against building.

What is *not* wrong here: the bot applied rule 4 correctly both times, and its instinct is
sound. An agent that writes its own safety rules and then certifies them is precisely the
failure this machinery exists to prevent. The defect is that the carve-out was drawn narrower
than the set of `CLAUDE.md` edits the repo compels a PR to make.

## Decision

Widen rule 4 in `.github/workflows/claude-review.yml` from one carve-out to three. Alongside
the existing (a) "Recent changes" case:

- **(b)** a brand-new per-directory `CLAUDE.md` added by the same PR that **creates** the
  directory it documents, sections included;
- **(c)** adding or removing a single list entry naming a path the same PR adds or deletes — a
  Key-files / sub-package entry, or a line in AGENTS.md's per-directory map.

Deliberately still blocking, because these are the cases where a human is genuinely the right
gate:

- any edit to the Purpose / Key files / Conventions / Invariants of a `CLAUDE.md` that
  **already existed** on the base branch — that rewrites rules already in force;
- *rewording* an existing list entry, as opposed to (c)'s mechanical add/remove;
- every other `AGENTS.md` edit, and all of `.github/`, `.claude/`, `.gitignore`;
- **override on (b):** if a new directory's `CLAUDE.md` contradicts, narrows, or grants itself
  an exception to any global invariant in `AGENTS.md`, the bot blocks anyway and quotes the
  offending line.

The safety argument for (b) is that a new directory's canon cannot loosen anything: it
constrains code that did not exist before the PR, the code itself is still reviewed against the
global invariants, and the file reads as a plain addition in the diff rather than a subtle edit
to something in force. (c) is verifiable rather than trusted — the bot must confirm the named
path really is added or deleted by the same diff.

## Consequences

- Package-adding milestones (M3–M6) can now go green on their own merits instead of costing an
  override each.
- The guardrail gets narrower in scope but sharper in signal: it stops crying wolf on mandated
  documentation, so a future block on an existing file's Invariants section means something
  instead of being the fifth false alarm waved through.
- The residual risk is an agent writing a weak invariant for its own new package. Three things
  bound it: the scope limit to newly created directories, the explicit override above, and the
  fact that a new file is fully visible in the diff the owner skims before merging.
- This ADR's change was itself blocked by rule 4 when proposed — correctly, since it does
  loosen the guardrails — and merged only after the owner read it. Revisit if the reverse
  failure ever shows up in review.
