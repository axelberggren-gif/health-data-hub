# 0001 — Record architecture decisions

- **Status:** Accepted
- **Date:** 2026-06-23

## Context
The owner is non-technical and most code is written by AI agents across many separate sessions.
Without a durable record, decisions get silently re-litigated or contradicted, and the owner has
no plain-language trail of what was chosen on his behalf.

## Decision
Keep lightweight ADRs in `docs/decisions/`. Significant/seam-level decisions get a numbered file.
Agents read this folder at session start; the `claude-review` bot flags diffs that contradict an
accepted ADR and softly suggests a new ADR when an architectural seam changes.

## Consequences
- A searchable history of *why*, readable by a non-technical owner.
- A small per-decision overhead (one short file) — accepted as worth it.
- ADRs are never a *required* status check, so they can't block a merge or stall automation.
