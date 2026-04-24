# TODOS

## Capital Budget

### Remove deprecated `autopilot_max_fund` compatibility alias

**What:** Remove the deprecated `autopilot_max_fund` compatibility alias after one release.

**Why:** `capital_max_fund` is the canonical global capital authority. Keeping the old Autopilot-scoped alias indefinitely would leave two apparent max-fund sources and make future budget behavior harder to reason about.

**Context:** The Global Capital Budget Authority plan keeps `autopilot_max_fund` as a one-release read alias so existing installs can migrate without losing their configured limit. After that compatibility window, remove alias handling from backend config, frontend compatibility tests, docs, and any mirrored API response fields.

**Effort:** S
**Priority:** P2
**Depends on:** Global Capital Budget Authority shipping with the compatibility alias for one release.

## Design Review

### Reduce Control Center overview card nesting

**What:** Rework the Control Center overview lower section so configuration, Autopilot, and Monitoring read as one operator workspace instead of three equal cards with nested cards inside them.

**Why:** The current first screen is state-first and clear, but the lower half still drifts toward dashboard-card mosaic. `DESIGN.md` says cards should exist only when the card is the interaction; here several cards are decorative containers around status facts.

**Context:** `/design-review` on 2026-04-24 fixed the dashboard chart contrast, mobile capital-stat clipping, and undersized trade/header touch targets. This remaining layout debt is broader than a tactical CSS fix and should be handled as a focused overview layout pass.

**Impact:** Medium
**Category:** Visual hierarchy / layout
**Effort:** M
**Priority:** P2

## Completed

### Apply suggested base order as guarded per-symbol entry sizing

**Completed:** v1.2.0.0 (2026-04-22)

**What shipped:** Added an explicit `autopilot_symbol_entry_sizing_enabled`
switch, extended the shared Autopilot policy seam to resolve entry-size
decisions alongside adaptive TP, routed ASAP and SymSignals through one shared
signal-runtime order-size resolver, persisted applied-vs-fallback sizing
metadata through buy executions, retried once with baseline `bo` on sizing
validation failures, and surfaced entry-sizing status in the Autopilot cockpit.

### Add owner-confidence summary to Control Center overview

**Completed:** v1.2.0.0 (2026-04-22)

**What shipped:** Added a compact owner-confidence summary to the Control
Center overview that rolls up operating mode, config trust, Autopilot memory,
and a lightweight live-data signal without duplicating Monitoring diagnostics.

### Add ranked scarce-bot admission for trusted symbols

**Completed:** v1.2.0.0 (2026-04-22)

**What shipped:** Added a shared ranked admission and reservation seam in
`backend/service/signal_runtime.py`, reused Autopilot trust memory to rank
favored, neutral, and cooling symbols, routed ASAP and SymSignals through the
same decision path, and expanded regression coverage around ranking,
explanations, and release-on-failure behavior.

### Finish the deferred backend stabilization slice for data/replay/database seams

**Completed:** 2026-04-08

**What shipped:** Removed redundant history-window wrappers from
`backend/service/data.py`, centralized numeric SQLite text-timestamp handling,
hardened replay archive reads/writes against short millisecond fixtures and
mixed timestamp inputs, reused the same timestamp normalization seam in
housekeeping, and extracted additive-column/corruption-message helpers from
`backend/service/database.py` with regression coverage.

### Harden config trust and invalidation in Control Center

**Completed:** v1.0.3.0 (2026-03-27)

**What shipped:** Added explicit Control Center config-trust states, quiet
auto-refresh for clean tabs, stale-draft conflict handling, browser-local
invalidation fanout after save, restore, and live activation, the `/config/all`
`config_updated_at` contract, and regression coverage for stale snapshot
timestamp handling.

### Create a repo-level DESIGN.md after the Control Center ships

**Completed:** 2026-03-21

**What shipped:** Added the repo-level `DESIGN.md` and then refined it with the
surface-treatment rule that keeps gradients atmospheric and working panels flat.
