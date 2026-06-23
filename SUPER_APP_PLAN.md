# Personal Health Super-App — Solution & Plan (v1 draft)

> One place that pulls in everything you track, shows you **how you're doing today**,
> explains **why**, and tells you **what to change** — then checks whether it worked.

*Draft for Axel to react to. Mark each idea in §6 with ✅ / ❌ / 🤔. Nothing here is built yet beyond what's noted in §1.*

---

## 1. Where we are today (the foundation already exists)

This repo is already a working, source-agnostic ingestion **backend** — not a blank slate. As of 2026-06-22 it holds real data:

| Source | Status | Data in the store |
|---|---|---|
| **WHOOP** (official v2 API) | ✅ Live, all scopes | ~6 months: 180 recovery days, 192 sleeps (+1,152 stage rows), 201 workouts, 185 cycles (2025-12-19 → 2026-06-22) |
| **Mill Sense** (bedroom air) | ✅ Live, polling | 526 readings, temp/humidity/TVOC/eCO₂ (2026-05-31 → 2026-06-22) |
| **Strava** | ⬜ Not yet | — |
| **Sleep Cycle** | ⬜ Not yet | — |

**What's built:** FastAPI + SQLAlchemy backend, a canonical (source-agnostic) data model, the `HealthDataSource` adapter pattern, idempotent sync with per-source cursors, an in-app scheduler/poller, and JSON/CSV export. A first cross-source visualization already exists: `bedroom_air_vs_sleep.html`.

**The point:** the hard plumbing (auth, normalization, dedup, a clean schema with raw payloads kept) is done. The "super-app" is the **three layers we haven't built yet**: more sources, an aggregated view, and an insight/coaching brain.

---

## Decisions & scope — locked 2026-06-23

**Decisions**
- **Insight model:** **Claude API** for the daily brief (C1) + ask-anything (C3). We send only *pre-computed summary features*, never raw data dumps — keeps cost negligible and exposure minimal. Built behind a model-agnostic `LLMProvider` seam so a local open model can be swapped in later via config. Correlations / anomalies / training-load (C2/C5/C6/C7) are plain statistics — **no model, no tokens**.
- **Client:** Responsive **web app (PWA)** for V1 (dashboard + insights), installable on phone. Native iOS comes later, with location (A12) + the Phase 5 sleep app.
- **Hosting:** **Local (your Mac)** for V1 — no push/digests yet, data stays put. Move to an always-on host (Fly.io / Render + Postgres) when automation/notifications arrive.

**V1 — see everything + cheap inputs** *(data you already have + easy external factors + light logging)*
- Dashboard: B1 Today view · B2 readiness score · B3 trends + anomaly flags · B4 timeline · B5 reports
- Inputs: A3 check-in · A5 alcohol/caffeine · A10 supplements *(one quick "daily log")* · A4 weather/daylight *(auto, free API)*
- Insights: C2 correlations · C5 illness early-warning · C6 training-load *(WHOOP-only until Strava)* · C1 daily brief · C3 ask-anything

**V2 — more inputs + the coach**
- A2 Apple Health → Sleep Cycle + steps + scale (A6) · A1 Strava *(gap-fill only)* · A7 Google Calendar → D5 recovery-aware calendar · A11 food + E5 photo food · D2 voice check-in · C4 weekly/monthly report · E1 experiments · **E2 goals + training goal-coach** · **E3 travel planning / jet-lag**

**Later — own the sensing (Phase 5)**
- G1–G5 custom sleep app · **G4 apnea screen** · A12 auto location + C7 sleep-by-location · A8 labs *(first blood test)* · F3 year-in-review · D1 push

**Parked** *(your no's; easy to revive)* — D3 digest · D4 air nudge · E4 share/FHIR · F1 voice assistant · F2 body-battery

> **Gated:** A12 (auto location, no manual tap) needs a passive background-location component on the phone — WHOOP carries no location — so it rides with the native app in Phase 5 (or a mini logger pulled forward if wanted sooner).

---

## 2. The vision — the core loop

The value isn't any single number; it's the **loop** that no single app (WHOOP, Strava, Sleep Cycle, Mill) closes on its own:

```
  INGEST              UNIFY               UNDERSTAND            ACT                 CLOSE LOOP
  everything   ─►   one timeline    ─►   "how am I &     ─►   "do this        ─►  "did it
  you track         + one score          why?"               today"               work?"
  (4 sources +      (readiness,          (cross-source        (daily brief,        (N-of-1
   context)          trends)              correlations)        nudges)              experiments)
```

The superpower is **cross-source "why."** WHOOP says recovery is 31% but never tells you it's because the bedroom hit 24 °C and 1,400 ppm CO₂, you trained late, and you'd had a drink. Your store has all of that on one timeline — so the app can.

---

## 3. Architecture — what to add

```
 SOURCES (adapters)          CANONICAL STORE          DERIVED LAYER           EXPERIENCE
 ┌───────────────┐          ┌───────────────┐        ┌──────────────┐       ┌──────────────┐
 │ WHOOP    ✅   │          │ recovery       │        │ daily_summary│       │ Dashboard    │
 │ Mill     ✅   │  ──►     │ sleep + stages │  ──►   │ baselines    │  ──►  │ "Today" view │
 │ Strava   ▢    │ normalize│ workout/cycle  │ nightly│ correlations │  api  │ Trends       │
 │ Sleep Cycle ▢ │          │ air quality    │  job   │ readiness    │       │ Daily brief  │
 │ Check-in  ▢   │          │ check-in*      │        │ anomalies    │       │ Ask-anything │
 │ Weather   ▢   │          │ + raw payloads │        └──────────────┘       │ Notifications│
 └───────────────┘          └───────────────┘                │              └──────────────┘
                                                      ┌───────▼────────┐
                                                      │ Insight engine │  Claude API over your
                                                      │ (LLM + stats)  │  data → brief + Q&A
                                                      └────────────────┘
```

Three new pieces on top of today's backend:
1. **Derived layer** — a nightly job that computes daily rollups, personal baselines (7/30/90-day), anomalies, and a unified **readiness score**. Stored in new tables so the UI is instant and the LLM gets pre-digested features.
2. **Insight engine** — statistics (what correlates with *your* good days) + Claude for the plain-English brief and "ask anything about my data."
3. **Experience** — a single dashboard + a daily brief + notifications. (Platform = open decision, see §7.)

Everything still flows through the existing adapter → canonical-store → consumer pattern, so none of this reworks the core.

### Data model — reserving room for what's coming

You'll likely add labs, supplements, food and location later. Design their homes in the canonical store **now** (empty tables / reserved fields) so adding each becomes *an adapter, not a schema scramble*. All follow the existing `SourceRecord` provenance + `raw` pattern:

- **`biomarker`** (blood tests / labs) — `taken_at`, `panel`, `marker` (ferritin, vitamin D, ApoB, HbA1c, …), `value`, `unit`, `ref_low`, `ref_high`, `flag` (low/normal/high). Source = manual form first, later a provider or Apple Health. **This is the "I did a blood test" home** — reserving it now makes logging a panel a 5-minute form instead of a migration.
- **`intake_event`** (supplements + medication) — `ts`, `name`, `kind` (vitamin/supplement/med), `dose`, `unit`. Lets you ask "magnesium at night → more deep sleep?"
- **`nutrition_entry`** (food) — `ts`, `description`, `calories` + macros, optional micros; source = manual / photo (Claude vision) / Apple Health.
- **Location-at-sleep** — `lat`/`lon` + a derived place label on the sleep session (or a small `place` table). Captured **on-device** at bedtime and joined to whichever sleep session covers that time — WHOOP detects sleep in the cloud with no location, so the location *must* come from your phone (a "going to bed" tap, the check-in, or the sensing app in Phase 5). Keep it coarse/on-device — location is sensitive.

Reserving these costs almost nothing today and future-proofs the store.

---

## 4. Data sources — honest reality check

- **Strava** — has a clean official OAuth2 API. Straightforward adapter like WHOOP. Adds what WHOOP lacks: GPS routes, pace, power, elevation, segments, and activities you log in other apps. *(Note: overlaps WHOOP workouts — we'd reconcile, not double-count.)*
- **Sleep Cycle** — ⚠️ **no public developer API** (to confirm). Realistic paths: (a) it already writes to **Apple Health** → we add an Apple Health adapter and get Sleep Cycle *plus* steps, mindfulness, weight, etc. in one move; (b) its manual CSV/data export; (c) scraping (fragile, not recommended). **Recommendation: bring Sleep Cycle in via Apple Health**, which is higher-leverage anyway.
- **Apple Health (or Google Fit)** — the umbrella that unlocks Sleep Cycle + a dozen other feeds at once. Strong candidate to add early.

### Build vs. integrate — which apps are worth owning

The rule: **rebuild only when the app's value is a thin sensing/UX layer over data you can capture yourself *and* it locks that data away.** Otherwise integrate.

| App | Verdict | Why |
|---|---|---|
| WHOOP | **Integrate** | Specialized hardware + years of sensor-fusion R&D — unrecreatable |
| Strava | **Integrate** | Value is the social / segments / maps *network*, not the tracking |
| Mill Sense | **Integrate** | Hardware you already own; just read its cloud |
| **Sleep Cycle** | **Replaceable** | Phone-sensor data + UX, **no public API**, and WHOOP already does the hard part (staging) |

**Don't clone Sleep Cycle — build the slice WHOOP can't.** Phone-based staging is weak (no HRV → poor REM detection); WHOOP already does staging well. What's worth owning is a small phone app that captures what *neither* WHOOP nor Mill exposes: **snore + room-noise events, a smart alarm, and location-at-sleep**, all `POST`ed to your backend as one more `HealthDataSource`. The payoff is a feature no off-the-shelf app can give you: cross your snore/noise timeline with WHOOP's respiratory rate + SpO2 dips for the same night → a rough **sleep-apnea / disordered-breathing screen**. Recommended order: (1) ingest Sleep Cycle via Apple Health now (near-zero effort, instant baseline), (2) build the thin sensing app later if you enjoy it, (3) skip the full clone. *(See Phase 5.)*

---

## 5. Proposed roadmap (phased)

| Phase | Goal | Headline deliverable |
|---|---|---|
| **0 — Foundation** | *Done* | Backend, canonical store, WHOOP + Mill live, export |
| **1 — Unify & see** | One aggregated view of what you already have | Nightly **daily-summary** layer + **"Today" dashboard** (readiness score, all sources on one screen, trends). Builds on the existing air-vs-sleep report. |
| **2 — Complete the picture** | Add the missing inputs + context | **Strava** + **Apple Health (→ Sleep Cycle)** + **daily check-in** + **weather/daylight** + **location-at-sleep**; scaffold the `biomarker` / `intake_event` / `nutrition_entry` tables |
| **3 — Understand & coach** | The "why" and "what to change" | **Correlation engine**, **daily brief** (Claude), **weekly review**, **ask-anything Q&A**, **notifications** |
| **4 — Optimize & close loop** | Make it act *for* you | **N-of-1 experiments**, **illness/overtraining early-warning**, goals/streaks, more sources (Oura/Garmin, **labs/blood markers**, calendar) |
| **5 — Own the sensing layer** *(optional)* | Capture what no app exposes | A small **phone sleep-sensing app**: snore + room-noise events, **smart alarm**, **location-at-sleep** — fused with WHOOP staging; unlocks the **sleep-apnea screen** |

Phase 1 gives you the "aggregated view" you asked for fastest, using data that's *already in the DB today*.

---

## 6. Ideas menu — say yes / no to each

Reply with the codes (e.g. *"yes to B1, B4, C2; no to E3"*). Markers: ⭐ high-leverage · ◐ nice · ○ later/optional.

### A. Data sources to add
- **A1 ⭐** Strava (routes, pace, power, elevation, non-WHOOP activities)
- **A2 ⭐** Apple Health umbrella → also pulls in Sleep Cycle, steps, weight, mindfulness
- **A3 ◐** Daily subjective check-in (mood / energy / stress / soreness, 1-tap)
- **A4 ◐** Weather + daylight/sunrise (outdoor temp, pollen, hours of daylight)
- **A5 ◐** Nutrition/alcohol/caffeine log (even just "drink y/n", "last caffeine time")
- **A6 ○** Smart scale / body comp (Withings/Apple Health) — table already exists
- **A7 ○** Google Calendar load (meeting density / travel as a stress & jet-lag proxy)
- **A8 ○** Labs / blood markers (periodic manual entry, or provider export)
- **A9 ○** Oura / Garmin / Apple Watch as additional wearables
- **A10 ◐** Supplement / vitamin log (what + when → "magnesium at night vs. deep sleep?")
- **A11 ◐** Food / nutrition tracking (scales up from A5; photo → Claude vision, see E5)
- **A12 ⭐** Location-at-sleep — auto-capture where you slept (drives C7)

### B. The aggregated view (Phase 1)
- **B1 ⭐** A single **"Today" dashboard**: readiness score + every source on one screen
- **B2 ⭐** Unified **readiness score** blending recovery + sleep debt + air quality (+ check-in)
- **B3 ⭐** **Trends**: 7/30/90-day baselines with anomaly flags (e.g. HRV drop streak)
- **B4 ◐** **Timeline view**: scrub any day and see all sources aligned hour-by-hour
- **B5 ◐** Auto-refresh the existing air-vs-sleep report; add workout-vs-recovery, etc.

### C. Understand & coach (Phase 3)
- **C1 ⭐** **Daily brief**: 3-sentence plain-English "here's last night, here's today, do X"
- **C2 ⭐** **Correlation discoveries** surfaced as cards ("late workouts cost you ~30 min REM")
- **C3 ⭐** **Ask anything** about your data in natural language (Claude over your store)
- **C4 ◐** **Weekly review** + a monthly report (auto-generated)
- **C5 ◐** **Illness / overtraining early-warning** (HRV↓ + resp-rate↑ + skin-temp↑ + eCO₂)
- **C6 ◐** **Training-load guidance** (acute:chronic workload from Strava + WHOOP strain)
- **C7 ◐** **Where do you sleep best** — sleep quality ranked by location / room / travel (needs A12)

### D. Daily experience & delivery
- **D1 ⭐** Morning **push notification** with the brief
- **D2 ◐** **"How I'm feeling"** one-tap check-in (emoji + optional voice note → Claude tags it)
- **D3 ◐** Weekly digest delivered to **email / Notion / Slack** (connectors available)
- **D4 ○** **Air-quality nudge**: "open a window — bedroom eCO₂ is 1,200 ppm before bed"
- **D5 ○** **Recovery-aware calendar**: auto-suggest lighter days when recovery is low

### E. Optimize & close the loop (Phase 4)
- **E1 ⭐** **N-of-1 experiments**: "keep the bedroom < 20 °C for a week — I'll measure the effect"
- **E2 ◐** **Goals & streaks** (sleep consistency, training balance)
- **E3 ○** **Travel / jet-lag mode** (timezone shift → adjusted targets)
- **E4 ○** Shareable read-only snapshot for a coach / doctor (or FHIR export)
- **E5 ○** Photo food logging (Claude vision → rough nutrition)

### F. Fun / stretch
- **F1 ○** Voice assistant ("how did I sleep this week?") on phone
- **F2 ○** "Body battery" live gauge that drains/recharges through the day
- **F3 ○** Year-in-review / personal records wrapped

### G. Own your own sensing — custom sleep app (Phase 5)
- **G1 ⭐** Snore detection + optional audio clips (the gem WHOOP can't capture)
- **G2 ◐** Smart alarm — wake you in a light-sleep window
- **G3 ◐** Room-noise / disturbance timeline (partner, traffic, baby)
- **G4 ⭐** Sleep-apnea screen — snore + WHOOP respiratory rate + SpO2 dips
- **G5 ○** Wake-mood capture on alarm dismiss

---

## 7. Open decisions I need from you

These shape Phase 1, so I've put a recommendation on each:

1. **Client platform** — *Recommend: a responsive **web app (PWA)*** first: one codebase, installable on your phone, supports push, fastest to a usable dashboard. Native mobile (React Native) later if you want deeper phone features. *(Alt: keep it report-only, no app.)*
2. **Hosting** — *Recommend: a small always-on host* (Fly.io / Render + Postgres) so syncs, the nightly job, and the morning brief run even when your laptop is closed. *(Alt: stay local + cron — fine if you only look on your machine.)*
3. **How much manual logging are you up for?** — drives A3/A5/D2. Even 10 seconds/day (mood + alcohol y/n) massively boosts the "why" engine. *(None / minimal / happy to log daily.)*

---

## 8. Suggested first move

If you greenlight Phase 1: build the **nightly daily-summary layer + a "Today" web dashboard** over the data already in the DB, reusing the air-vs-sleep work. That turns six months of WHOOP + three weeks of Mill into the single aggregated view — and gives the insight engine its foundation — without waiting on any new source.
