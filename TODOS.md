# TODOS

## Deferred

### Extend sidestep campaign analytics beyond grouped replay polish

**What:** If operators later need deeper reporting, add a campaign-first
analytics surface or read model that rolls up cumulative PnL, time-in-mission,
and leg sequencing across one sidestep campaign.

**Why:** Grouped replay, waiting-campaign status, and compact campaign summary
copy now cover the release-safe operator story, but they still stop short of a
dedicated campaign analytics view.

**Pros:** Could improve campaign-level evaluation, make long multi-leg missions
easier to compare, and create a clearer base for future reporting or
Autopilot-facing summaries.

**Cons:** Adds reporting and read-model complexity on top of the already
cross-cutting sidestep persistence model, and it is not required for the
current operator workflow.

**Context:** If this is picked up later, start from the shipped grouped replay
and waiting-campaign status surfaces before deciding whether a new read model is
actually warranted.

**Depends on / blocked by:** Only worth doing if operator feedback shows the
current grouped replay and waiting-campaign context are still insufficient.

## Completed

### Build the operator-facing Backtest UI after backend core stabilizes

**Completed:** v3.3.0.0 (2026-05-28)

**What shipped:** Added a Backtest route with strategy replay controls,
Lightweight Charts candles and buy/sell markers, stats, run metadata,
previous-run comparison, loading and safe error states, responsive layout, and
frontend helper coverage for request shaping, marker normalization, and
comparison math.

### Centralize lifecycle normalization across backend and frontend config seams

**Completed:** Unreleased (2026-05-12)

**What shipped:** Added one canonical lifecycle normalization seam on each
side, made `trade_mode` the operator-facing source of truth, routed backend
capability checks and frontend config load, submit, readiness, and validation
through the shared helpers, and added regression coverage for canonical-mode
round trips.

### Confirm waiting sidestep campaigns keep owning capacity while flat

**Completed:** Unreleased (2026-05-12)

**What shipped:** Kept the chosen campaign-ownership policy instead of adding a
second scheduler, verified that flat waiting campaigns continue to preserve
their reserved slot and capital semantics, covered watcher re-entry and manual
activate paths with regression tests, and closed the old
"prioritize waiting campaigns over new symbols" follow-up as an
audit-and-validation item rather than new ranking behavior.

### Polish waiting-campaign status and grouped sidestep mission history

**Completed:** Unreleased (2026-05-12)

**What shipped:** Added explicit waiting-campaign cooldown, last-exit, and
re-entry status fields to the existing payloads and UI, kept the main closed
trades table terminal-first, and added grouped mission summary context to
sidestep replay so operators can read campaign progression without a new
analytics service or DB table.

### Untangle order-persistence ownership between Orders, Trades, and order_persistence

**Completed:** Unreleased (2026-05-12)

**What shipped:** Moved sell-side lifecycle writes behind
`order_persistence`, replaced external calls to private trade-cache
invalidation with a public seam, preserved the read/query role of `Trades`,
and added regression coverage around partial sells, terminal closes, manual
adds, stop handling, and related execution flows.

### Deduplicate the EMA20 swing and reverse strategy pair

**Completed:** Unreleased (2026-05-12)

**What shipped:** Extracted the shared EMA20 swing runtime and persistence
skeleton into one shared core, kept the public bullish and reverse strategy
modules stable, preserved separate persisted state namespaces, and collapsed
the mirrored strategy tests into a shared parameterized suite plus
direction-specific assertions.

### Reduce Control Center overview card nesting

**Completed:** v1.4.0.0 (2026-04-28)

**What shipped:** Reworked the Control Center overview lower section into one
shared operator workspace for Configuration, Autopilot, and Monitoring;
flattened the preview shells so the three surfaces read as related subsections
instead of equal nested cards; softened the owner-confidence summary to match
the overview shell; and added frontend regression checks so the preview
components stay out of full-card wrappers.

### Remove deprecated `autopilot_max_fund` compatibility alias

**Completed:** v1.4.0.0 (2026-04-28)

**What shipped:** Removed the one-release `autopilot_max_fund`
compatibility alias from backend runtime config, frontend config loading and
submit payloads, and mirrored API surfaces; switched the remaining capital and
Green Phase logic to the canonical `capital_max_fund` key; rejected removed-key
config writes and legacy backup restores; filtered removed keys from new backup
exports; and documented the breaking upgrade requirement in the release notes
and config or API docs.

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
