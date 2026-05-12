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

### Centralize lifecycle normalization across backend and frontend config seams

**What:** Replace the duplicated `trade_lifecycle_mode` /
`sidestep_campaign_enabled` normalization spread across backend and frontend
helpers with one canonical mapping path per side.

**Why:** The current compatibility logic is repeated across config loading,
submit payloads, and validation helpers, so every lifecycle change pays a
multi-file drift tax.

**Pros:** Lowers the chance of backend/frontend disagreement, makes
compatibility behavior easier to reason about, and reinforces
`trade_lifecycle_mode` as the canonical operator-facing key.

**Cons:** Crosses both backend and frontend config plumbing, so it is wider
than a release-safe cleanup and needs careful regression coverage for old
snapshots and payloads.

**Context:** If picked up later, start from the typed lifecycle view in
`backend/service/config_views.py`, then simplify the matching normalization in
frontend config load and submit helpers.

**Depends on / blocked by:** Depends on the release-safe sidestep cleanup and
docs alignment landing first so the canonical key is already established.

### Untangle order-persistence ownership between Orders, Trades, and order_persistence

**What:** Stop splitting trade and order write responsibility across
`Orders`, `Trades`, and `order_persistence`, including private cache
invalidation calls such as `Trades._clear_order_cache()`.

**Why:** This is the strongest hidden-coupling seam in the execution path and
makes buy or sell persistence changes harder to reason about safely.

**Pros:** Clarifies write ownership, reduces private cross-service reach-in,
and makes future execution-path changes safer to test and review.

**Cons:** Touches sensitive buy and sell persistence paths, so the eventual
refactor is invasive and needs strong regression coverage around cache
invalidation and execution history.

**Context:** If picked up later, map the current write flow through
`backend/service/orders.py`, `backend/service/trades.py`, and
`backend/service/order_persistence.py` before choosing the final ownership seam.

**Depends on / blocked by:** Best done after the current release-safe cleanup,
when execution-path behavior is otherwise stable enough for a focused refactor.

### Deduplicate the EMA20 swing and reverse strategy pair

**What:** Extract the shared logic behind `ema20_swing.py` and
`ema20_swing_reverse.py`, and do the same for their mirrored tests.

**Why:** Any behavior fix for that strategy pair currently has to be applied in
four places, which increases maintenance cost and drift risk.

**Pros:** Aligns with the repo's DRY preference, cuts copy-paste maintenance,
and makes future strategy fixes less error-prone.

**Cons:** Needs careful design so the shared seam stays explicit instead of
turning into a clever abstraction that hides the directional differences.

**Context:** If picked up later, compare both runtime modules and both test
files side by side first, then extract only the truly shared mechanics and keep
the direction-specific behavior obvious.

**Depends on / blocked by:** No hard prerequisite, but best kept separate from
sidestep cleanup so strategy refactors do not blur release-focused changes.

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
