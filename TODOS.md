# TODOS

## Completed

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
