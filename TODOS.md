# TODOS

## Next up

### Periodic price re-evaluation for open trades

**Status:** Identified 2026-11-03 during the YB/USDC stuck-trade investigation (incident: the trade sat above its TP for ~23h without an exit evaluation, and the later manual sell filled ~15% below the stale displayed price). Scope fixed by owner decision 2026-11-07: **implement the exit price guard only; the periodic re-evaluation loop is rejected** (stream recovery stays the watchdog's job; in a flat market a periodic refresh discovers nothing; the accepted silent-stream blind spots are documented as known limitations).

**What (decided scope):** Before a market sell decided by the engine, and before a market fallback when a limit sell runs in a timeout (or fails to place), fetch the live bid and re-verify that the exit is still justified — TP/trailing/autopilot-timeout require the fresh price at or above their threshold, stop-loss requires it at or below the SL price. Abort the sell (fail-closed, position stays open) when the fresh price no longer justifies it or the fetch fails. Engine-computed guard bounds shared through one pure helper at both call sites; TP limit-timeout fallback behavior unchanged. Document the per-reason guard behavior, the zero-steady-state API-load budget, and the interaction with `watcher_ohlcv` mode.

**Why no periodic refresh:** Classic DCA TP/SL checks run only when a `ticker_price` event arrives from the per-symbol trade stream; a dead or silent stream (watchdog per-symbol budget is `max(1800s, candle timeframe)`, 1006 disconnects, quiet pairs, or demo/testnet books) leaves open trades unmanaged while the UI keeps showing stale prices. A periodic REST refresh was the original mitigation, declined on 2026-11-07 for steady-state API load and the flat-market no-op argument; the guard closes the failure mode that actually cost money (executing a sell on a stale trigger price) without any periodic work.

**Plan of record:** `~/.gstack/projects/TBMoonwalker-moonwalker/open-trade-price-revaluation-plan-20261107.md`

**Effort:** M

**Priority:** P2

### Prepare request bodies and OHLCV helpers for future major upgrades

**Status:** Litestar 2.25.0 and pandas 3.1.0 expose deprecation warnings during
CI on 2026-10-23. All 1,855 backend tests pass on these versions.

Before upgrading Litestar to 3.x, replace unmarked `data` request parameters
with explicit body markers such as `JSONBody[...]` in backtest, configuration
and strategy controllers. Preserve strict payload validation and verify the
existing malformed/unknown-field regression tests.

Before upgrading pandas to 4.x, replace deprecated `inplace=True` DataFrame
operations in `backend/service/data_ohlcv.py` with explicit assignments. Verify
candle timestamps, resampling, duplicate removal and history serialization.
Do not suppress the warnings or bundle either major upgrade into a lock refresh.

**Priority:** P2

### Denylist from open trade: symmetric re-enable + DESIGN.md badge pass

**Status:** Ready to design when picked up

**What:** v4.9.0.0 ships a one-way "Deny from new entries" row action with
config-only undo by editing `pair_denylist`. A symmetric "Re-enable" /
"Remove from denylist" row action, plus a DESIGN.md pass on the "Denylisted" tag
color/label, would close the loop. Keep it an entry-only change; do not touch
open trades.

**Effort:** M

**Priority:** P3

### Add the recovery DCA status card to the vitest coverage guard

**Status:** Follow-up from the v4.15.0.0 pre-landing review (P3, informational).

**What:** The new `RecoveryDcaStatus.vue` component is not in the vitest
`coverage.include` list, so its rendering branch is excluded from the reported
coverage even though `recovery-dca-status.test.ts` exercises it. Ratchet the
component into `frontend/vitest.config.ts` `coverage.include`, verify the
component-level tests assert the card surface, and reinstate the surface
assertions the old `recoveryDcaSurface.test.cjs` guard checked before they moved
to the card.

**Context:** v4.15.0.0 moved the recovery DCA diagnostics out of
`OpenTradeExpandedRow.vue` into the reusable `RecoveryDcaStatus.vue` card. The
CJS guard was intentionally reduced to a single delegation assertion
(`OpenTradeExpandedRow` renders
`<RecoveryDcaStatus :trade="rowData" />`), and the new component coverage lives in
`frontend/tests-vitest/recovery-dca-status.test.ts`. The card is correct today;
this only tightens the guard so a future edit to the card surface or a
coverage-include regression is caught.

**Effort:** S

**Priority:** P3

### Remove the three deferred Phase 4 data-compat shims at their concrete floors

**Status:** Deferred by the 2026-11-01 legacy-migration-removal review (D8=A). Each removal is safe only once its recorded floor is passed.

**What:** Remove the three Phase 4 data-compat shims that the shipped 4.9.0.0 MSV floor does not gate: the CSV fee-accounting fallback in `backend/service/trade_math.py` (fee flag, migration 016), the legacy CSV import path, and the `legacy_accumulation_graph` view. Each as a small PR with its fixture/test updated, the same shape as the two shims removed this wave (replay backfill >008, `has_legacy_partial` >007).

**Why:** These three postdate the 4.9.0.0 floor or are not version-gateable at all, so removing them now would break fee accounting on supported 4.9–5.2 installs. Deferring keeps the wave removal-only and ships only what the floor proves safe.

**Pros:** Each removal gates on a concrete, recorded floor: the fee flag at >=5.3.0.0 (016 provenance, commit 04b6990), the CSV import behind a file-format deprecation window, and `legacy_accumulation_graph` on a retention window since 4.0.0.0/c44fd0e (legacy-shape docs persist unmigrated). The shims are read-only fallbacks, so running one more cycle is harmless.

**Cons:** Three fallback paths stay in the codebase past their natural window until the floors are re-checked.

**Context:** Decided in the 2026-11-01 legacy-migration-removal eng review (D8, option A); the two gateable shims landed this wave on `chore/hygiene-logging-serialization-sync-2026-10`. Plan of record: `~/.gstack/projects/TBMoonwalker-moonwalker/legacy-migration-removal-plan-20261101.md`.

**Depends on:** The MSV floor in `backend/service/msv.py` and its record in `docs/operations.md`; the CSV import also needs an operator-visible deprecation window before its removal.

**Priority:** P3

### Decide the migration-ledger prune policy (Phase 5 ledger hygiene)

**Status:** Deferred by the 2026-11-01 legacy-migration-removal review (D6=B); not a PR this wave.

**What:** Decide the retention policy for `schema_migrations` and `config_migrations` rows, which currently grow unbounded across releases. Candidate: a one-time "prune applied ledger rows older than MSV" migration plus a collapse of the `015` (`2026-10-23-015-accumulation-dust-archive`) and `003` (`2026-07-28-003-trade-ledger-expand`) near-duplicate, both gated by MSV and checksum-safe.

**Why:** The ledgers are the only record that a database has applied each migration, but nothing trims them, so every install accumulates one row per applied step forever.

**Pros:** Bounds ledger growth and removes the near-duplicate entry; a gated, checksum-safe step keeps the recovery contract intact.

**Cons:** Pruning touches the recovery contract (the checksums are the resume proof), so the policy must be designed before any row is deleted; a wrong prune makes a healthy database look un-migrated.

**Context:** Phase 5 of the legacy-migration-removal plan; its "What NOT to do" section forbids deleting ledger rows outright, so pruning must go through a gated, checksum-safe step. Deferred via D6 (option B) on 2026-11-01.

**Depends on:** The MSV floor in `backend/service/msv.py`; the checksum contract in `backend/service/schema_migrations.py`.

**Priority:** P3

### Classify backups before restore confirmation

**Status:** Deferred owner decision from the May 2026 trade-modes-reset CEO plan; the original deferral to TODOS.md was never written. Recorded 2026-11-01 (D12=A).

**What:** Quoted verbatim from the trade-modes-reset CEO plan "Deferred to TODOS.md" section: "Add a restore/import review state that classifies backups as Dynamic DCA, Sidestep, or deprecated static before restore confirmation".

**Why:** The restore flow silently drops legacy bridge keys from pre-4.9 backups (this wave's D11), so an operator restoring an old backup gets no indication of what representation the backup carried; a classification screen before confirmation would make that legible.

**Pros:** Restores an explicitly made owner decision to the backlog where it was supposed to live; implementation stays a future wave, with zero scope change to the removal wave.

**Cons:** New restore-flow UI work (a classification screen) unrelated to the removal wave; the underlying silent key-drop behavior stays unexplained until this ships.

**Context:** The trade-modes-reset CEO plan (2026-05-12, branch `feature/code-stabilization`) deferred this item to TODOS.md; the 2026-11-01 legacy-migration-removal eng review (D12, option A) recorded the missing entry.

**Depends on:** Nothing — standalone restore-flow addition, buildable in any future wave.

**Priority:** P3

### Show an unavailable notice on replay charts without indicator series

**Status:** Declined option of D19 (2026-11-01 design review), tracked per D22/R10.

**What:** A muted "Indicator overlays unavailable for this trade" caption on the replay chart when the indicator fetch yields no series (also fixes the existing swallowed-404 case).

**Why:** D19 deferred it to keep the wave removal-only; legacy rows without a deal id now render candles without indicator overlays and no explanation, and without a repo-side record the deliberate silence is undiscoverable in ~6 months.

**Pros:** Honest state per DESIGN.md ("missing feeds are shown as unavailable rather than invented"); fixes a pre-existing silent case (swallowed 404 in `loadReplayIndicators`).

**Cons:** New chart state + copy (~3h human / ~20min CC).

**Context:** `frontend/src/components/TradeReplayChart.vue` `loadReplayIndicators` (silent early return + swallowed 404); the D19 record in the legacy-migration-removal plan.

**Depends on:** Nothing — standalone chart-state addition, buildable in any future wave.

**Priority:** P3

### Extend the campaign residue gate to the full 021 drop set

**Status:** Hardening candidate from the 2026-11-02 pre-landing review (F5, red-team 6/10); the current gate scope is an approved, documented design decision.

**What:** The campaign-residue gate (startup `_assert_no_open_trade_campaign_residue` in `backend/service/database.py` and restore `_assert_no_open_trade_campaign_residue` in `backend/service/backup_restore.py` — the two implementations must stay in sync) aborts startup / refuses a restore only when an `opentrades` row carries `campaign_id IS NOT NULL`. The seven sidestep-era waiting-state columns that migration 021 drops (`waiting_reference_price`, `reserved_reentry_quote`, `waiting_reference_amount`, `waiting_reference_quote`, `virtual_waiting_profit`, `virtual_waiting_profit_percent`, `last_transition_at`) are zeroed silently on rows that still carry them. Extend the assertion to the full drop set (campaign reference OR non-zero waiting state) with a fixture test.

**Why:** In 4.8.x the waiting-state writers were campaign-context paths that propagated `campaign_id`, so the flagged scenario needs an already-inconsistent row on an unsupported 4.8.x direct upgrade. The risk is low and the current scope was approved; recorded rather than extended in this wave.

**Context:** Pre-landing review of `chore/hygiene-logging-serialization-sync-2026-10` (2026-11-02), finding F5; operator decision 2026-11-02 (PR note + TODO, no code change this wave).

**Priority:** P3

## Dashboard history

### Evaluate server caching and incremental timeline loading

**Status:** Proposed; browser caching and profit-tab persistence are implemented.

**What:** Measure repeated timeline resampling under concurrent dashboard use.
Consider a short-lived server cache with snapshot-write invalidation first,
then an additive delta cursor only if measurements justify it. Preserve the
existing full response and verify bucket updates, disconnect recovery, and
retention cleanup. Configurable snapshot cadence is a separate optional step.

**Design:** [Dashboard history loading](docs/designs/delta-loading.md).
Open trades remain full-state and closed history remains paginated.

## Control Center verification

### Verify remaining rendered accessibility observations

**Status:** Follow-up verification from the historical source audit; not a
claim that the current UI has these defects.

**What:** Check rendered dark-mode contrast, mobile pagination touch targets,
and the intentional scope of compact table typography against DESIGN.md.
The old theme-ownership concern is already addressed by the shared theme store.

## Denylist concurrency

### Review stale full-form saves against concurrent denylist appends

**Status:** Design follow-up; atomic append is implemented.

**What:** The append endpoint preserves concurrent appends, but full config
saves replace the list. Verify stale-form conflict handling and decide whether
server-side revision checks are needed to avoid silently losing a newer deny.
Preserve the ability to intentionally remove tokens through configuration.

**Design:** [Denylist semantics](docs/designs/denylist-symbol-from-open-trade.md).

## Frontend staging guard

### Harden the frontend-staging guard against partial and masked-out failures

**Priority:** P1

**What:** The new frontend-staging guard (shipped v4.7.0.0) was left as-is at
the 2026-09-13 pre-landing review after deferred findings:
- **F1 (P2):** a partial deploy (entrypoint `index.html` present but a referenced
  JS bundle missing) passes both `frontend_staging_warning()` and the
  `run.sh` stage check, so a dead dashboard returns HTTP 200. The underlying
  deploy gap predates this branch; the guard should verify the bundles the
  entrypoint references and carry a partial-deploy regression test.
- **F2 (P2):** Litestar masks `HTTPException.detail` to a generic
  "Internal Server Error" body, so the actionable "run ./run.sh start" message
  the guard was built to surface never reaches the browser. Replace the 500
  raise with a controlled error body and assert its HTTP response.
- **F3 (P3):** `app.py` startup calls `frontend_staging_warning()` with a
  synchronous `Path.is_file()` on the event loop before the timing wrapper;
  move the probe off the loop to match the request path.

**Deferred from:** pre-landing review on `feature/code-optimizations` (v4.7.0.0).
The guard is strictly an improvement over the previous bare 500; hardening is
non-blocking.


## Retired

### Extend sidestep campaign analytics beyond grouped replay polish

**Retired:** 2026-09-26 documentation cleanup. Sidestep has been removed; its
proposed campaign analytics are no longer an active backlog item. The former
discovery gate had no confirmed evidence issues. Historical completed Sidestep
items below remain release history, not descriptions of current capabilities.

## Completed

### AI-trust and capital-budget config section coverage guards

**Completed:** v5.1.0.0 (2026-10-07)

**What shipped:** Closed both pre-landing P3 coverage gaps for the new
AI-trust and capital-budget config sections. (1) Pinned the
`capitalBudgetPreview` client mirror to the backend admission math with a
cross-language contract test,
`backend/tests/test_capital_budget_preview_parity.py`, that recomputes the same
shared vectors `frontend/tests-vitest/capital-budget-preview.test.ts` asserts, so
a math drift on either side fails its own test; aligned the preview's
negative-buffer handling to `normalize_buffer_pct` (clamp <= 0 to no buffer,
behavior-preserving since the input has `min=0`). (2) Added dedicated mount tests
asserting each section's control surface:
`config-ai-trust-section.test.ts` (field labels, the warn-block switch staying
inert until the cockpit is enabled, and the exposed `validate()`) and
`config-capital-section.test.ts` (the title fallback plus the gated
showBaseFields / showExpertFields / dynamicDcaEnabled fields and `validate()`).
These components are not in the vitest `coverage.include` ratcheted set, so the
new mount tests harden regression coverage without moving the ratchet; see the
separate P3 for ratcheting the Recovery DCA status card into the include guard.

### Fix mobile Backtest chart marker label clipping (ISSUE-002)

**Completed:** 2026-08-02

**What shipped:** Added exact feature-local logical-range padding based on the
actual first- and last-candle marker text, typed the Lightweight Charts payloads,
and guarded pre-paint rendering with invocation ownership and fail-open padding.
Added 100 percent viewport-helper coverage, component lifecycle regressions,
and stable 375 x 812 left/right Playwright snapshots. The real localhost
default Backtest now shows the complete `take_profit` label with no page overflow
or console errors.

### Fix mobile text truncation (ISSUE-003, ISSUE-004)

**Completed:** v4.5.0.0 (2026-07-28)

**What shipped:** Reworked the Control Center mission header and Statistics
mobile layout so guidance, tabs, and activity labels remain readable at 375
pixels, aligned responsive breakpoints at 767 pixels, and added desktop,
tablet, and mobile Playwright coverage.

### Fix Statistics pagination (ISSUE-001)

**Completed:** v4.0.4.0 (2026-06-05)

**What shipped:** Added `sortedAndPaginatedSymbols` computed property that correctly
sorts and slices the symbol data based on pagination state. The data table now
uses `remote` mode with explicit `@update:page` and `@update:sorter` handlers,
so clicking pagination numbers actually changes the displayed data.

### Fix Statistics sort column data reduction (ISSUE-002)

**Completed:** v4.0.4.0 (2026-06-05)

**What shipped:** Rewired the sort handler to work with the new computed pagination
pipeline. Clicking a sort column header now correctly sorts the full dataset and
shows a full page of results instead of reducing to 3 rows. Added `columnSortOrder`
helper to keep sort indicator logic DRY across all sortable columns.

### Polish Statistics heatmap density and Strategy Builder graph readability

**Completed:** v4.0.0.0 (2026-05-31)

**What shipped:** Tightened the Statistics Trade Activity panel with compact
padding and an inline closed-trade activity summary, removed duplicate heatmap
computed state, and made Strategy Builder graph labels easier to read by using
a less aggressive Rete fit scale plus larger node and control typography.

### Build the operator-facing Backtest UI after backend core stabilizes

**Completed:** v3.3.0.0 (2026-05-28)

**What shipped:** Added a Backtest route with strategy replay controls,
Lightweight Charts candles and buy/sell markers, stats, run metadata,
previous-run comparison, loading and safe error states, responsive layout, and
frontend helper coverage for request shaping, marker normalization, and
comparison math.

### Centralize lifecycle normalization across backend and frontend config seams

**Completed:** v4.2.0.0 (2026-07-26)

**What shipped:** Added one canonical lifecycle normalization seam on each
side, made `trade_mode` the operator-facing source of truth, routed backend
capability checks and frontend config load, submit, readiness, and validation
through the shared helpers, and added regression coverage for canonical-mode
round trips.

### Confirm waiting sidestep campaigns keep owning capacity while flat

**Completed:** v4.2.0.0 (2026-07-26)

**What shipped:** Kept the chosen campaign-ownership policy instead of adding a
second scheduler, verified that flat waiting campaigns continue to preserve
their reserved slot and capital semantics, covered watcher re-entry and manual
activate paths with regression tests, and closed the old
"prioritize waiting campaigns over new symbols" follow-up as an
audit-and-validation item rather than new ranking behavior.

### Polish waiting-campaign status and grouped sidestep mission history

**Completed:** v4.2.0.0 (2026-07-26)

**What shipped:** Added explicit waiting-campaign cooldown, last-exit, and
re-entry status fields to the existing payloads and UI, kept the main closed
trades table terminal-first, and added grouped mission summary context to
sidestep replay so operators can read campaign progression without a new
analytics service or DB table.

### Untangle order-persistence ownership between Orders, Trades, and order_persistence

**Completed:** v4.2.0.0 (2026-07-26)

**What shipped:** Moved sell-side lifecycle writes behind
`order_persistence`, replaced external calls to private trade-cache
invalidation with a public seam, preserved the read/query role of `Trades`,
and added regression coverage around partial sells, terminal closes, manual
adds, stop handling, and related execution flows.

### Deduplicate the EMA20 swing and reverse strategy pair

**Completed:** v4.2.0.0 (2026-07-26)

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
