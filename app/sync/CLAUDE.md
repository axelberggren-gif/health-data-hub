> **Canon** — current source of truth for this directory. If reality and this file disagree,
> fix this file in the same PR.

# app/sync/ — idempotent persistence + cursors

## Purpose
The shared write path every source uses, so re-running a sync never duplicates data.

## Key files
- `orchestrator.py` — `upsert(db, model, *, source, source_external_id, values)` and
  `get_cursor` / `set_cursor`. **This is an architectural seam: changing the upsert contract
  requires an ADR.**

## Conventions
- `upsert()` finds the row by `(source, source_external_id)`, inserts if missing, otherwise
  updates the given `values`, and returns `(obj, created)`. **The caller commits** the session.
- Cursors store the incremental watermark per `(source, resource)`.

## Invariants (do not break)
- All persistence of source-derived records goes through `upsert()` keyed on
  `(source, source_external_id)` — never a raw `db.add()` that a re-sync could duplicate.
- The identity key matches the `UniqueConstraint("source", "source_external_id")` on each
  canonical table — the DB is the backstop if anyone bypasses `upsert()`.
- See `tests/test_orchestrator_idempotency.py` — that test guards this invariant; keep it green.

## Recent changes
- Documented the persistence invariant + added the idempotency test (initial setup).
