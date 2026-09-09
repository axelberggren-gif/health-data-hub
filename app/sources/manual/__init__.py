"""Manual input (the daily log) as a normal data source — tech spec D3.

The check-in and the supplement log are not a special case bolted onto the API: they are a
`HealthDataSource` like WHOOP or Mill, mapping their payload into canonical models through
the same idempotent `upsert()`. The only difference is how the data arrives — a POST from
the owner's phone instead of a poll — which is why `backfill()` / `sync_incremental()` are
no-ops, the same way `handle_webhook()` is the arrival path for a push-based source.
"""

from .source import CHECKIN_KEY_PREFIX, ManualSource, checkin_key

__all__ = ["CHECKIN_KEY_PREFIX", "ManualSource", "checkin_key"]
