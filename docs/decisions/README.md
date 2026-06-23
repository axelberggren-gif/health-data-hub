# Architecture Decision Records (ADRs)

This folder is the **memory of why** the project is built the way it is. Each significant
technical decision gets one short, numbered file. It exists so that:

- the owner (non-technical) has a plain-language record of decisions made on his behalf, and
- future AI agents read past decisions and **don't silently contradict them** (the
  `claude-review` bot flags diffs that conflict with an accepted ADR).

## When to add an ADR

Add one when a PR changes an **architectural seam** or makes a decision that's expensive to
reverse. Concretely, that includes changes to:

- `app/sources/base.py` — the source contract
- `app/models.py` — the canonical data model
- `app/sync/orchestrator.py` — the persistence contract
- choice of a new dependency, database, hosting, or auth approach

For ordinary changes (a new source that follows the existing contract, a bug fix, docs) you do
**not** need an ADR. The review bot will *suggest* one only for seam changes — it never blocks
on a missing ADR.

## How to add one

1. Copy `0000-template.md` to the next number, e.g. `0004-add-postgres.md`.
2. Fill in Context / Decision / Consequences. Keep it short (half a page).
3. Set Status to `Accepted` (or `Proposed` if you want discussion first).
4. Commit it in the same PR as the change it describes.

## Index

- [0001 — Record architecture decisions](0001-record-architecture-decisions.md)
- [0002 — AI-first guardrails on a public GitHub repo](0002-ai-first-guardrails.md)
- [0003 — Pragmatic typing & lint baseline](0003-typing-and-lint-baseline.md)
- [0004 — Pin claude-code-action to a known-good commit](0004-pin-claude-code-action-to-known-good-commit.md)
