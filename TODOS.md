# TODOS

## Deferred

### Prioritize eligible waiting campaigns over brand-new symbols when capacity is constrained

**What:** Prefer an eligible `flat_waiting_reentry` campaign over a brand-new
symbol when capital or bot-slot admission is scarce.

**Why:** The approved sidestep design treats re-entry as part of one ongoing
campaign, but v1 intentionally makes waiting campaigns compete normally for
capacity. That keeps the first release simpler, yet it can still leave a
sidestepped symbol stranded while fresh symbols consume the available slots.

**Pros:** Preserves the operator mental model that one campaign stays alive
until TP, improves continuity after tactical exits, and makes future
campaign-aware ranking feel more intentional.

**Cons:** Adds scheduling policy on top of the already-more-complex campaign
lifecycle and interacts with the shared admission guard plus campaign-owned
re-entry rules.

**Context:** If this lands later, the likely implementation seams are the
shared admission flow in `backend/service/signal_runtime.py` and the future
campaign summary/admission read model.

**Depends on / blocked by:** Depends on v1 `SpotCampaigns`, the shared
campaign-aware admission guard, and the waiting-campaign summary read model
shipping first.

### Add campaign-level analytics and grouped history for sidestep missions

**What:** Add campaign-level analytics and grouped history so operators can see
the cumulative PnL and leg sequence for one sidestep campaign, not only the
individual leg closes.

**Why:** The approved v1 keeps lifecycle truth and `ClosedTrades` semantics
clean, but it still reports leg summaries first. That is enough to ship safely,
yet it makes multi-leg campaigns harder to evaluate as one mission.

**Pros:** Improves operator trust in the campaign model, makes performance of a
multi-leg sidestep easier to understand, and creates a cleaner base for future
reporting or Autopilot features.

**Cons:** Adds reporting and read-model complexity on top of the already
cross-cutting persistence changes, and it is not required for the core v1
lifecycle to work.

**Context:** If this is picked up later, the likely seams are the future
`SpotCampaigns` read model, `backend/service/statistic.py`,
`backend/service/data.py`, and the closed-trades / waiting-campaign frontend
surfaces.

**Depends on / blocked by:** Depends on v1 `campaign_id` propagation,
`close_reason` policy updates, and the waiting-campaign/read-model foundations
landing first.

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
