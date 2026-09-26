# Design (Spike + Spec): Delta Loading for Large Archive Data

Generated: 2026-09-25
Branch: main
Repo: TBMoonwalker/moonwalker
Status: P0 IMPLEMENTED; P1/P2/P3 PROPOSED
Mode: Spike -> Spec -> Eng-review -> P0 implemented (client-side SWR); P1-P3 remaining

## Problem Statement

Moonwalker streams "live" data over WebSockets and loads chart/history data over
REST, mostly as full-state (the entire set, re-sent wholesale). The original ask:
"delta loading for big archive data like in the overall section or opentrades",
i.e. send *what changed* instead of *everything* every tick.

The eng-review reframed the ask around two costs that are easy to conflate:

1. **Perceived reload cost.** A full page reload (`F5`, tab reopen) wipes the
   in-memory Pinia store, so the "overall" / uPNL timeline is re-fetched and
   re-shipped on **every reopen**, even when minutes-old data is already on screen.
   The user sees a spinner and a full re-render every time.
2. **Server compute cost.** Under multiple dashboard clients (a normal
   deployment, per AGENTS.md), each client's revalidate re-triggers a server-side
   resample.

The cheapest, lowest-risk move is to fix (1) with **client-side web storage**
(stale-while-revalidate), then layer server-side savings on top. That is the P0/P1
split below.

### Correction to the original premise

The original spike claimed the overall/uPNL timeline "resamples the whole
`UpnlHistory` table." That is not true. `statistic.py:476` already windows the
query to the last 12 months:

```python
model.UpnlHistory.filter(timestamp__gte=year_start)    # year_start = now - 365d
```

The table can grow unbounded (default `upnl_housekeeping_interval = 0` = infinite
retention, `housekeeper.py:34,138`), but the timeline query and pandas resample are
**already bounded to ~12 months regardless of table size.** The original "Phase 1a:
window the query" was a no-op and was removed. The real remaining costs are the
uncached per-client resample (P1) and the reload re-fetch (P0).

## Spike Findings: what the code actually does today

**Real-time trades are full-state push, and that is correct.**

- `backend/service/websocket_fanout.py` runs a producer every 5s and keeps only the
   latest payload per fanout (subscribers are `maxsize=1` queues that drop older
    messages, `:123-133`), then broadcasts the whole payload. It cannot replay a
    backlog.
- `backend/controller/trades.py` producers serialize the full set each tick; the
   closed feed pushes page-0 only (`get_closed_trades()` with no page arg ->
     `CLOSED_TRADES_PAGE_SIZE = 10`, `service/trades.py:57`), so it is a
    "recently-closed" mini-feed, not the archive.
- `frontend/src/stores/websocket.ts` is a **full replace** (no diffing).
- The "statistics" WS (`App.vue:33`, `buildWsUrl('/trades/closed')`/`open`/
    `unsellable` at `App.vue:162-172`) carries the profit-overall headline scalar
   (`Statistics.vue:137`), a single number, trivially cheap. Not an archive.

**Closed trades are already paged.**

- `CLOSED_TRADES_PAGE_SIZE = 10` (`trades.py:57`), REST `/trades/closed/{page}` +
   `/trades/closed/length` (`controller/trades.py:142-161`), consumed in
    `frontend/src/components/ClosedTrades.vue:91,103`. The archive grows in pages,
    not as one unbounded array.
- `UpnlChart.vue:63-86` also feeds the chart's `data` array from a *second* source
   (a live WS point, `pushRealtimePoint`, deduped by 15-min bucket). Any cache
    change must coexist with that dedup.

**The overall/uPNL section is the perceived-cost target.**

- `UpnlHistory` (`model/upnlhistory.py`): auto `id` PK, indexed `timestamp`,
    `upnl`/`profit_overall`/`funds_locked`.
- `get_profit_overall_timeline` (`service/statistic.py:463`) windows to 12 months,
   resamples via pandas, and has **no server-side cache** (contrast
    `PROFIT_CACHE_TTL_SECONDS = 2` for profit, `:27`). `frontend/src/stores/upnl.ts`
   refetched it wholesale every 5 min. A full reload wiped that in-memory cache and
   forced a blocking re-fetch on every reopen.

**The codebase already has a guarded web-storage idiom.**

- `themeStore.ts:46,60` reads/writes `localStorage` inside try/catch ("tolerating a
   missing or blocked localStorage"; "Storage may be blocked ... degraded
   gracefully").
- `configSnapshotStore.ts:311-318` writes a `localStorage` invalidation marker in a
   try/catch.
- No shared helper; each caller inlines its own guard. P0 centralises this.

## Per-Stream Reality (corrected)

| Stream / section | Growth model | Today | Fix |
|---|---|---|---|
| **overall / uPNL timeline** | table unbounded (retention 0), but query windowed to 12 months; no server cache | blocking re-fetch on every reload + per-client resample | **P0 client SWR (done)**, P1 server cache, P2 `?since` |
| **open trades** | bounded, mutated in place (`profit`, `tp_limit_*`, `dca_*`) | full set over WS every 5s | **none - correct as full-state** |
| **closed trades** | unbounded but **already paged** (10/page REST + count) | paged REST archive + 10-row live feed | **none - already paged; defer** |
| **unsellable trades** | bounded small set | full set over WS every 5s | none |

## P0 — Client-side web storage, stale-while-revalidate (IMPLEMENTED this pass)

**Goal:** kill the *perceived* reload cost. Paint the "overall" chart instantly from
a warm web-storage cache after a page reload, then reconcile in the background.
No API change; lowest risk; reuses the existing guarded-storage idiom.

**Files changed:**
- **`frontend/src/helpers/safeStorage.ts` (new):** `readJSON` / `writeJSON` /
    `removeJSON`, each tolerating blocked/unavailable storage (private mode,
    locked-down profile, full quota, non-browser context). Centralises the guard
     `themeStore` and `configSnapshotStore` inlined; tested in
      `tests-vitest/safeStorage.test.ts`.
- **`frontend/src/stores/upnl.ts`:** at store creation, seed `data` from
    `localStorage['mw_upnl_overall_timeline']` (via `readJSON`) for an instant
    first paint; after every successful fetch, persist the authoritative snapshot
    back via `writeJSON` with a `storedAt` marker.
- **`frontend/src/components/UpnlChart.vue`:** (a) `isLoading` now starts from
    `data.value.length === 0` so a warm cache paints with no spinner; (b) the
    `onMounted` catch sets `showEmptyState = data.value.length === 0` so a failed
    background revalidate keeps the cached view instead of blanking the chart.

- **`frontend/src/stores/profit.ts`:** the daily/monthly/yearly profit tabs share one
    store and one `/statistic/profit/{ts}/{period}` endpoint — a separate, *uncached*
    data source from the uPNL timeline. It now seeds `dataByPeriod` from
    `localStorage['mw_profit_history']` and persists the whole per-period map after
    each successful load, so every profit tab paints instantly on reload and
    reconciles in the background — the same SWR pattern, keyed by `profit.ts`'s
    per-period shape so a later load never evicts an earlier period.
- **`frontend/src/components/Charts.vue`:** `isLoading` now starts from
    `Object.keys(get_profit_history_data(period)).length === 0` so a warm cache
    paints with no spinner; the background revalidate is unchanged.

**Behavior:**
```
reload -> readJSON(seed) -> chart paints instantly from cached points (no spinner)
       -> onMounted load_upnl_history_data() runs in the background
       -> on 200: data = fresh; writeJSON(persist) ; next reload is warm
       -> on failure: cached view is kept (no clobber, no blank)
```

**Scope kept deliberately small:**
- P0 now spans **both** timeline data sources: the uPNL overall timeline
   (`upnl.ts` / `UpnlChart.vue`) **and** the daily/monthly/yearly profit tabs
   (`profit.ts` / `Charts.vue`) — both stale-while-revalidate, both guarded by
    `safeStorage.ts`.
- Reconcile is a **full snapshot** today (the on-mount load already does it). P2
   turns that into an incremental `?since` delta.
- `writeJSON` persists only the fetched snapshot; the ephemeral live WS tail point
   is re-pushed on reconnect, so it is not persisted. (Refinement only.)
- No TTL gate on first paint: the background revalidate keeps it fresh; a stale or
   very old entry still reconciles, so serving the last-known view is the correct
   degraded state.

**Tests added (`tests-vitest/upnl.test.ts`, `tests-vitest/profit.test.ts`):**
`upnl.test.ts` — seeds `data` from a warm cache with **no** network call;
cold-cache starts empty; persists on success; paints warm then reconciles to fresh;
a blocked `setItem` does not throw and does not clobber; a failed revalidate leaves
the cached `data` intact. `profit.test.ts` mirrors the same matrix for the
daily/monthly/yearly tabs — seeds every period from a warm cache with no fetch,
persists the whole per-period map on load, never evicts an earlier period, serves a
second same-TTL load from the in-memory cache, and does not throw on a blocked write.
`safeStorage.test.ts` covers round-trip, missing key, corrupt entry, and blocked
read/write no-throws.

## Profit tab keep-alive (in-page switch — IMPLEMENTED this pass)

P0 caches the **data** across *page reloads*; a **tab switch** (within one session)
is a *lifecycle* concern P0 does not cover. The profit tabs (Overall / Daily /
Monthly / Yearly) rendered each chart behind `v-if`, so switching **destroyed and
recreated** the `Charts` / `UpnlChart` instance — ECharts re-initialized and replayed
its entrance animation, and `onMounted` re-fired its load — which *felt* like a
fetch even though the in-memory cache was serving the data.

**Files changed:**
- **`frontend/src/views/TradesView.vue`:** each profit `n-tab-pane` now sets
    `display-directive="show"`, which alone keeps its chart mounted — the
    previously-redundant child `v-show` on `activeProfitTab` was removed, since
    naive-ui’s per-pane directive already toggles the whole pane with `v-show`. A
    tab switch is a pure show/hide: no remount, no re-animate, no `onMounted` refetch.
    `Charts.vue` and `UpnlChart.vue` both use `autoresize`, which re-sizes a chart
    when its container transitions hidden → visible.
- **`frontend/tests/profitChartsAverage.test.cjs`:** the profit source-snapshot
     assertions now assert the bare child form (`<UpnlChart />`, `<Charts period="…" />`),
     a `display-directive="show"` co-located with each pane’s `getProfitTabProps(…)` (160-char
     window), and a `>= 4` count — locking the keep-alive in *and* a redundant child
     `v-show` out.

**Trade-off:** all four profit charts now initialize once at the profit section's
mount instead of lazily on first view (four small ECharts instances — negligible).
The trades section (open / closed / unsellable) was intentionally left on `v-if`:
open trades is a live stream and closed trades is paginated, so keep-alive there has
different implications and is out of scope. This is a client-only UI change: no new
cache, no server cost, and the one-shot `onMounted` reconcile per tab (a warm reload
still fires one background revalidate on first view, because `loadedAtByPeriod` is
left unseeded) remains the intended SWR behavior.

**naive-ui 2.45.3 gotcha + live verification (this pass):** an early attempt placed
`display-directive="show"` on the parent `<n-tabs>` — a **no-op** in this naive-ui
version. `filterMapTabPanes` in
`node_modules/naive-ui/es/tabs/src/Tabs.mjs` reads the directive from **each
`<n-tab-pane>`**'s own props (`vNode.props.displayDirective`), so it now sits on all
four profit panes. The guard in `profitChartsAverage.test.cjs` was strengthened from a
mere `/display-directive="show"/` presence check to a per-pane co-occurrence + `>= 4`
count check, and was proven non-vacuous by a mutation test (dropping one pane's
directive fails the suite).

**Browser-verified on `:8130`** (running instance reloaded into the deployed
bundle `index-BzZvZpZR`, no backend restart): 6 tab switches across Daily /
Monthly / Yearly (twice) produced **0** `/statistic/profit` requests, **0** long
tasks, **4** chart canvases retained, every switch **<= 19 ms**, and each revealed
chart resizes 749x190 via `autoresize` (no blank or 100x100 canvas). Re-confirmed
after the redundant child `v-show` was removed — the per-pane `display-directive`
alone sustains the keep-alive. This confirms P0’s client cache + the per-pane
keep-alive together make an in-page tab switch cost no network request and no
perceptible delay.

## P1 — Server-side resample cache (PROPOSED)

`get_profit_overall_timeline` (`statistic.py:463`) re-runs the pandas resample on
every call with **no server cache**. Wrap it (or the row read it depends on) in
the existing `helper.async_ttl_cache(maxsize=1, ttl=~30-60)` (the idiom at
`statistic.py:405`, with `cache_clear()` from `helper/async_cache.py:38`), and
clear it when a new snapshot persists (`_store_upnl_snapshot`, `statistic.py:412`).

This collapses **N concurrent client revalidates** (P0 makes them background) into
one server resample per window. Independent of P0; recommended as the next step for
the *server* cost under multi-client use. No client change.

## P2 — `?since` delta cursor on the timeline (PROPOSED, after P1)

Mirror the incremental idiom that **already exists for candles** in
`service/data.py` (`required_since`, `latest_timestamp`,
`__get_dataframe_for_symbol_since`, `:257/372/620`) rather than inventing a new one:

```
GET /statistic/profit-overall/timeline               -> full 12-month adaptive timeline (unchanged, P1-cached)
GET /statistic/profit-overall/timeline?since=id      -> {"cursor": <max_id>, "points": [rows with id > since]}
```

Upnl snapshots are **append-only** (only the housekeeper deletes them,
`housekeeper.py:135-153`), so no tombstones are needed. The client (`upnl.ts`)
records the `cursor` after a snapshot and polls `?since=cursor`; a stale/unresolved
cursor (after a housekeeper prune) falls back to a full refresh. Upgrades P0's
background revalidate from full to incremental.

## P3 — Config-driven snapshot cadence (PROPOSED, optional, independent)

`snapshot_interval_seconds = 60` is hardcoded (`statistic.py:34`). Expose it near
`upnl_housekeeping_interval` so operators can throttle `UpnlHistory` row growth
without a code change.

## Out of scope (by decision)

- **Open-trades delta** — bounded, in-place-mutating; full-state is correct.
- **Closed-trades delta** — already paged at 10/page with a count endpoint.

## Design Decisions

- **D0 - Lead with P0 (client SWR).** Perceived reload cost is the dominant symptom
   and P0 removes it with no API change and minimal risk, reusing the in-repo
   guarded-storage idiom. (Done this pass.)
- **D1 - P1 (server cache) is the next step.** P0 makes client revalidates
   background; P1 keeps the server from resampling them. They compose (D0 then D1).
- **D2 - Cursor = monotonic `id`, append-only semantics for upnl.** Not a timestamp
   cursor. Mirror `service/data.py`, not a new `?since_id` invention (reuse ladder).
- **D3 - Open trades stay full-state; closed trades stay paged.** Already mitigated.
- **D4 - Endpoints additive, default = back-compat.** No-arg
   `profit-overall/timeline` keeps returning the full adaptive timeline;
    `?since` is opt-in.
- **D5 - No tombstones.** Upnl is append-only; reconcile = full refresh on a stale
   cursor. The original `removed` mechanism is dropped.
- **D6 - Reconcile triggers:** disconnect, TTL expiry, and an unresolved cursor
   (after a housekeeper prune).
- **D7 - `snapshot_interval_seconds` to config (P3), independent.**

## Risks / Edge Cases

- **Housekeeper prune** (`housekeeper.py:135-153`, when
   `upnl_housekeeping_interval > 0`) can delete old rows a P2 cursor assumed survive.
   Mitigated by reconcile-on-unresolved-cursor (D6).
- **Pandas resample is stateful** (adaptive 15min/4h/1d/1w buckets). Appending raw
   new points and letting the chart auto-fit the tail is acceptable; verify the
    chart tolerates appended points (P2 acceptance).
- **P1 cache staleness under active trading.** The 30-60s TTL + `cache_clear()` on
   each new snapshot bounds staleness to the snapshot cadence. The P0 client cache
   does the same on the client side.
- **Web storage quota / blocked (P0).** `safeStorage.ts` degrades every access to a
   no-op; tests cover blocked read/write.
- **`UpnlChart` dedup.** The live WS tail (`pushRealtimePoint`) coexists with the
   seeded `data` because of its 15-min-bucket dedup; the P0 catch keeps the cached
   view on a failed revalidate.

## Success Criteria

- P0: a page-reopen paints the "overall" chart instantly from `localStorage` with no
   spinner and no blocking fetch; a failed background revalidate does not blank or
    clobber the chart.
- P1: multi-client deployment resamples the 12-month timeline at most once per cache
   window, not once per client.
- P2: steady-state `?since` returns only appended points since the cursor, and a
   client recovers after a disconnect and after a housekeeper prune.
- No caller breaks: the no-arg timeline response, the paged closed-trades feed, and
   the `statistics` WS headline are unchanged.
- Open-trades and closed-trades deltas are documented out of scope.
- Tests: `safeStorage.test.ts`, `upnl.test.ts`, `profit.test.ts` (P0); P1 cache test; P2
   since-cursor + reconcile; back-compat regression keeps
    `tests/statistic_upnl_history.cjs` / `get_profit_overall_timeline` green.

## Next Steps

1. **P0 (done this pass):** `safeStorage.ts` + `upnl.ts` seed/persist +
    `UpnlChart.vue` SWR tweaks + `upnl.ts`/`profit.ts` seed+persist + `UpnlChart.vue`/`Charts.vue` SWR tweaks +
     `safeStorage.test.ts`/`upnl.test.ts`/`profit.test.ts`. Verified
     with `npm run type-check` and `vitest run`.
2. **P1 (next):** short-TTL `async_ttl_cache` on the timeline resample +
    `cache_clear()` in `_store_upnl_snapshot`. Backend test + `cd scripts && ./ci.sh`.
3. **P2 (after P1, only if still worth it):** additive `?since` cursor mirroring
    `service/data.py`; `upnl.ts` polls deltas and reconciles on a stale cursor.
4. **P3 (optional):** make `snapshot_interval_seconds` config-driven.
5. **Do not build:** open-trades or closed-trades delta.

## Distribution

P0 is frontend-only (Vue/Vite -> `backend/static/`); backend serves it. P1 is
backend-only. P2 adds a query param + a store change. No new distribution surface.

---

## ENG REVIEW REPORT (plan-eng-review)

Target: `docs/designs/delta-loading.md`.
Verdict: **APPROVE-WITH-CHANGES** - directionally correct; one material premise error
and one missed reuse; re-scoped to P0/P1/P2/P3. P0 implemented and tested this pass.

### Confirmed (evidence)
- **Premise error (P1's old "Phase 1a" removed).** `statistic.py:476` already
   filters `timestamp__gte=year_start` (windowed to 12 months). The "window the
    query" idea was a no-op.
- **Perceived cost was the real target.** A reload wipes the Pinia store
    (`upnl.ts`), forcing a blocking re-fetch on every reopen. Client web storage
     (SWR) is the cheapest fix -> P0.
- **Server cost is real but separable.** No server cache on
    `get_profit_overall_timeline` (`:463`, contrast `PROFIT_CACHE_TTL_SECONDS=2`
     `:27`); multi-client is normal -> P1.
- **Delta idiom already exists.** `service/data.py` candle fetch is cursor/incremental
    (`requried_since`..., `:257/372/620`). P2 mirrors it.
- **Guarded-storage idiom already exists.** `themeStore.ts:46,60`,
    `configSnapshotStore.ts:311-318`. P0 centralises it in `safeStorage.ts`.
- **Append-only.** `_store_upnl_snapshot` creates rows (`:412`); the only deleter is
    the housekeeper (`:135-153`). No tombstones (D5).
- **Closed trades already paged** (`CLOSED_TRADES_PAGE_SIZE=10`,
    `ClosedTrades.vue:91`); out of scope.

### Blocking issues
- (resolved) **P1's "window the query" was a no-op** - removed; replaced by P0 (client
   SWR) + P1 (server cache).
- (resolved) **missed reuse** of `service/data.py` and the guarded-storage idiom -
   P0/P2 now point at them.

### Non-blocking
- Reconcile mechanism simplified from tombstones to full-refresh-on-stale-cursor
   (D5), because upnl is append-only.

### Scope
PASS after re-scope. Open-trades and closed-trades deltas documented as out of
scope, not omitted. P0 (client SWR) shipped and tested; P1/P2/P3 proposed.
