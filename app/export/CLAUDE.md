> **Canon** — current source of truth for this directory. If reality and this file disagree,
> fix this file in the same PR.

# app/export/ — JSON / CSV export

## Purpose
Read the canonical store and emit JSON / CSV (a zip) — the foundation for downstream consumers
(a personal app, analytics, an AI coach).

## Key files
- `exporter.py` — the export logic over the canonical models.

## Conventions
- Read from the **canonical models** (`app/models.py`) only — not a source's native payload.
- Exports are generated artifacts; they contain personal data and are **gitignored** (`exports/`,
  `*.csv`). Never commit an export.

## Invariants (do not break)
- Consumers depend on the canonical shape; if you add a field, add it to the canonical model
  first, then surface it here.
- No personal/health data written to a tracked path — only to the gitignored `exports/`.

## Recent changes
- Documented the canonical-only + no-commit rules (initial setup).
