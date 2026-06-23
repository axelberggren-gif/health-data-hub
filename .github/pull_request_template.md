## What
<!-- One sentence describing the change. -->

## Why
<!-- 1–3 bullets on motivation. -->

## Related issues
<!-- "Closes #N" auto-closes the issue on merge; "Refs #N" links without closing. -->
- Closes #

## How (only if non-obvious)
<!-- Brief notes on the approach. -->

## Checklist
- [ ] `make check` passes locally (ruff, format, mypy, pytest)
- [ ] No secrets or personal/health data added to any tracked file (this repo is PUBLIC)
- [ ] New logic in `app/sources/`, `app/sync/`, or `app/export/` has a test (or the PR says why not)
- [ ] If a new data source: it subclasses `HealthDataSource` and doesn't touch the sync/export/db layers
- [ ] If persistence changed: it goes through `orchestrator.upsert()` on `(source, source_external_id)`
- [ ] If an architectural seam changed (`base.py` / `models.py` / `orchestrator.py`): an ADR was added in `docs/decisions/`
- [ ] `CHANGELOG.md` updated (newest first)

## Test steps
<!-- How to verify this works locally. -->
1.
2.
