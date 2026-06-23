# Health Data Hub

A backend that pulls your health data from **WHOOP** (via the official WHOOP v2
Developer API) into a **source-agnostic canonical store**, and exports it as
JSON/CSV — the foundation for your own health app. Designed so more sources
(Apple HealthKit, the goose BLE/raw path, Oura, Garmin) and more uses
(analytics, AI coach) plug in without reworking the core.

> The archived [`b-nnett/goose`](https://github.com/b-nnett/goose) iOS app was
> the reference for *how to get WHOOP data*. We use the **official API** instead
> of its reverse-engineered BLE path; goose's SQLite schema informed the
> canonical model, and its BLE core is a candidate future adapter.

## Architecture
```
WHOOP v2 API ─┐
Mill Sense    ─┼─►  HealthDataSource adapters ─► normalize ─► Canonical Store
HealthKit*    ─┤        (app/sources/*)                         (app/models.py)
goose BLE*    ─┤                                                    │
Oura/Garmin*  ─┘                  Consumers: Export (JSON/CSV) · Analytics* · AI Coach*
* = future, seams already in place
```
- `app/sources/base.py` — the `HealthDataSource` interface every source implements.
- `app/sources/whoop/` — the WHOOP source: `oauth`, `client` (pagination + 429 backoff),
  `mapper` (WHOOP→canonical), `source` (`WhoopApiSource`).
- `app/sources/mill/` — the Mill Sense source: `auth` (username/password), `client`
  (device discovery), `mapper`, `source` (`MillSenseSource`) — indoor air quality.
- `app/sync/orchestrator.py` — idempotent `upsert` on `(source, source_external_id)` + cursors.
- `app/models.py` — the canonical schema (recovery, sleep+stages, workout, cycle, profile,
  body, **air quality**, vitals).
- `app/export/` — JSON / CSV-zip export over the canonical model.

## Setup
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then fill in WHOOP credentials
```
1. Create an app at <https://developer-dashboard.whoop.com> → copy **Client ID** / **Client Secret**.
2. Register the redirect URI **exactly** as `http://localhost:8000/auth/whoop/callback`.
3. Put `WHOOP_CLIENT_ID` / `WHOOP_CLIENT_SECRET` in `.env`.

You need an active **WHOOP membership** to authorize against your own data.

### Mill Sense (indoor air quality)
The [Mill Sense](https://millnorway.com/product/mill-sense/) reports temperature,
humidity, TVOC and eCO₂ to the Mill cloud. There's no OAuth — it uses your **Mill
app account** login. Add to `.env`:
```bash
MILL_USERNAME=you@example.com   # your Mill app email
MILL_PASSWORD=your-mill-password
# MILL_API_BASE=https://api.millnorwaycloud.com   # default; override only if needed
```
The cloud returns only the **latest** reading per device, so air-quality history is
built by polling on a schedule (see below) rather than a one-shot backfill.

## Run
```bash
uvicorn app.main:app --reload
```
- `GET /` · `GET /health` · interactive docs at `/docs`
- `GET /auth/whoop/login` → consent → callback stores tokens
- `POST /sync/whoop_api/backfill?days=30` → pull history into the store
- `POST /sync/whoop_api/incremental` → pull everything new since last sync
- `POST /sync/mill_sense/incremental` → capture one air-quality reading per sensor
- `POST /sync/mill_sense/backfill?days=7` → best-effort historical air quality
- `GET /mill/diagnose` → dump raw Mill payloads (confirm the history endpoint)
- `GET /export/json` · `GET /export/csv` → take your data out

### Collecting air quality overnight
One `mill_sense/incremental` call records a single snapshot — Mill only serves
the *latest* reading, so a time series is built by polling. Each poll upserts
one `air_quality_reading` row per sensor, keyed to the minute, so re-runs are
idempotent and distinct minutes accumulate.

**Option A — built-in poller (recommended).** Enable it in `.env` and the app
polls itself; restrict it to a nightly window so it only samples while you sleep:
```bash
MILL_POLL_ENABLED=true
MILL_POLL_INTERVAL_SECONDS=300
MILL_POLL_START_HOUR=22   # 22:00–08:00 (wraps midnight); omit both for 24/7
MILL_POLL_END_HOUR=8
```

**Option B — external cron** (if you'd rather not run the poller in-process):
```bash
*/5 * * * * curl -fsS -X POST http://localhost:8000/sync/mill_sense/incremental
```

### Retroactive backfill
`POST /sync/mill_sense/backfill?days=21` pulls *past* air quality from Mill's
statistics endpoint, which returns **hourly** (and daily) history per metric —
confirmed against a live GL-Sense, with roughly **3 weeks** of retention. Each
hourly bucket becomes one `air_quality_reading`, so you can backfill the last
few weeks of nights and align them with sleep immediately.

If a different Mill sensor model returns a shape we don't map, inspect it with:
```bash
curl -s http://localhost:8000/mill/diagnose | jq .
```
That dumps each sensor's `lastMetrics` and raw `/statistics` payloads; extend
the metric tables in `app/sources/mill/history.py` to match.

## Add a new source
1. Create `app/sources/<name>/source.py` implementing `HealthDataSource`.
2. Map its payloads into the canonical models (`upsert` keyed on `(source, source_external_id)`).
3. Register it in `app/sources/registry.py`. Sync + export work automatically.

## Notes / next steps
- `init_db()` auto-creates tables for dev. For production, switch to **Alembic** migrations.
- OAuth CSRF `state` is stored in-memory (single-process dev). Use signed cookies / Redis in prod.
- Backfill runs synchronously; move to a background worker for large ranges + webhooks.
- Verify WHOOP field names/units against the live API on first sync (esp. `hrv_rmssd_milli`);
  the full payload is kept in each row's `raw` column as a safety net.
- Same for Mill Sense: confirm `lastMetrics` keys/units (`temperature`, `tvoc`, `eco2`, …)
  on the first real poll — the raw device payload is preserved in `raw` for re-mapping.
