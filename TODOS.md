# TODOS

## Next up

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

### Upgrade frontend major dependencies: jsdom 31, TypeScript 7, @types/node 26

**Status:** Recorded 2026-11-06 as the hold list of the 2026-11-06 frontend dependency hygiene pass (patch/minor wave applied in the same day: axios 1.21.0, vite 8.3.6, vitest 5.1.0, vue 3.5.45, vue-tsc 3.3.14, @playwright/test 1.65.0, knip 6.44.1).

**What:** Bump the three held major-version frontend dev dependencies in dedicated, separately tested changesets:
- `jsdom` 30.1.3 -> 31.0.0 (vitest test environment; review jsdom 31 breaking changes against the 48-file vitest suite and coverage ratchet).
- `typescript` 6.0.3 -> 7.0.2 (compiler major; run `vue-tsc` type-check, build and the coverage ratchet, watch for removed/deprecated checker APIs used by tooling).
- `@types/node` 24.19.2 -> 26.x (hold until the repo's Node floor moves: `.nvmrc` and `frontend/package.json` engines pin Node 24.x, so 26 typings describe a runtime the project does not run; revisit together with a Node 26 upgrade decision).

**Why:** Recorded rather than bundled: major bumps need the compatibility review the dependency hygiene policy requires, and the axios 1.21.0 wave proved the test suite is the right gate for behavior changes (its header-default recognition change passed clean).

**Priority:** P3

### Upgrade Python major dependencies: multidict 7, python-dateutil 4

**Status:** Recorded 2026-11-07 as the hold list of the 2026-11-07 Python dependency hygiene pass (patch/minor wave applied the same day: ccxt 4.5.92, cachetools 7.3.0, pandas 3.1.1, python-socketio 5.18.1, websockets 17.4, ta-lib 0.8.3, anyio 4.16.0, click 8.5.1, mypy 2.4.1, pip 26.3, pytest 9.2.0, pytest-asyncio 1.4.1.post1, ruff 0.17.4, filelock 4.2.9).

**What:** Bump the two held major-version Python dependencies in dedicated, separately tested changesets:
- `multidict` 6.9.1 -> 7.2.1 (transitive of aiohttp and hard-pinned by ccxt: ccxt 4.5.92 still pins `multidict==6.9.1` and aiohttp 3.14.5 requires `multidict<7`, so the resolver cannot move it until a future ccxt release relaxes the pin; revisit together with the next ccxt major).
- `python-dateutil` 3.0.0 -> 4.0.0 (direct pin in `backend/requirements.in` carrying the "reviewed timezone engine for pandas, including post-2038 TZif support" comment; a major of pandas' reviewed timezone engine — verify pandas 3.x, tortoise-orm and litestar date parsing under dateutil 4, and re-check the post-2038 TZif rationale against the 4.x release notes).

**Why:** Recorded rather than bundled: major bumps need the compatibility review the dependency hygiene policy requires, and multidict is additionally unresolvable today because of ccxt's hard pin. Note: idna stays at 3.18 for the same reason (ccxt 4.5.90-4.5.92 all hard-pin `idna==3.18`), so the idna 3.20 "outdated" row is expected to persist.

**Priority:** P3

### Split service/orders.py into the dca/ package and a mode-neutral facade

**Status:** Identified 2026-11-06 during the accumulation Telegram notification investigation; follow-up cleanup, not part of that fix.

**What:** `service/orders.py` (legacy `Orders` class, from the 2025-09-17 upstream merge) predates the `dca/` subpackage carved out in `7bc61fe` (2026-10-26, "organize trading modes around shared exchange execution"). That refactor moved the DCA-owned mechanics into `dca/` but left `orders.py` at the service root, where it now mixes: (a) classic DCA order lifecycle finalization (persist + stats + the two `MonitoringService.notify_trade` calls at `orders.py:504`/`:621`), (b) the mode-agnostic placement reconciliation entry point `reconcile_placement_intents` (`orders.py:319`), which routes accumulation intents to the injected `accumulation_recovery` callback (`orders.py:100`, wired in `app.py:213-215`), and (c) the legacy-mutation lifecycle guard for accumulation symbols (`orders.py:106-144`). The refactor commit message says "DCA finalization ... owned by its mode", yet the finalization still lives in the root facade. Move the DCA-only finalization into `dca/` (keeping `dca/` as the layer `orders.py` imports from, not the reverse), keep the mode-neutral reconciliation and lifecycle routing at the service root (adjacent to `placement_reconciliation.py`, which already owns the routing), and reduce `orders.py` to a thin compatibility facade or remove it once `signals/*`, `app.py`, `runtime_services.py`, `trading_controls.py` and `dca/engine.py` point at the new locations.

**Why:** The ambiguity is not cosmetic: the missing accumulation Telegram notification was easier to miss precisely because "the order service" looks like a DCA module while still hosting accumulation seams. A clear mode boundary makes it obvious which mode owns trade finalization (and its notifications).

**Context:** 2026-11-06 investigation of missing accumulation trade notifications (see also `docs/monitoring.md` scope drift). Keep this split out of the notification fix diff.

**Effort:** M

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

## Completed

### Periodic price re-evaluation for open trades

**Status:** Completed 2026-11-07 as the exit price guard (G1: fresh-bid
verification before engine-decided market sells; G2: fresh-bid verification
before market fallback after a limit timeout or placement failure for non-TP
exits). Identified 2026-11-03 during the YB/USDC stuck-trade investigation
(incident: the trade sat above its TP for ~23h without an exit evaluation, and
the later manual sell filled ~15% below the stale displayed price). Scope fixed
by owner decision 2026-11-07: **implement the exit price guard only; the
periodic re-evaluation loop is rejected** (stream recovery stays the watchdog's
job; in a flat market a periodic refresh discovers nothing; the accepted
silent-stream blind spots are documented as known limitations). See "Exit
Price Guard" in `docs/configuration.md`.

**What shipped (decided scope):** Before a market sell decided by the engine,
and before a market fallback when a limit sell runs in a timeout (or fails to
place), fetch the live bid and re-verify that the exit is still justified —
TP/trailing/autopilot-timeout require the fresh price at or above their
threshold, stop-loss requires it at or below the SL price. Abort the sell
(fail-closed, position stays open) when the fresh price no longer justifies it
or the fetch fails. Engine-computed guard bounds shared through one pure
helper at both call sites; TP limit-timeout fallback behavior unchanged.
Documented the per-reason guard behavior, the zero-steady-state API-load
budget, and the interaction with `watcher_ohlcv` mode.

**Why no periodic refresh:** Classic DCA TP/SL checks run only when a
`ticker_price` event arrives from the per-symbol trade stream; a dead or
silent stream (watchdog per-symbol budget is `max(1800s, candle timeframe)`,
1006 disconnects, quiet pairs, or demo/testnet books) leaves open trades
unmanaged while the UI keeps showing stale prices. A periodic REST refresh was
the original mitigation, declined on 2026-11-07 for steady-state API load and
the flat-market no-op argument; the guard closes the failure mode that actually
cost money (executing a sell on a stale trigger price) without any periodic
work.

**Plan of record:** `~/.gstack/projects/TBMoonwalker-moonwalker/open-trade-price-revaluation-plan-20261107.md`

**Effort:** M

**Priority:** P2
