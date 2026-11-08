# TODOS

## Next up

### Add an operator repair path for quarantined classic-DCA placement intents

**Status:** Recorded 2026-11-07 during investigation of a reported startup lockout after upgrading to the latest main. The same-day fix (below) removed the most common trigger; this entry is the remaining operator-exit gap.

**What:** A quarantined placement intent (`quarantined`/`restored_quarantined`) keeps the fail-closed startup gate in `app.py` (`reconcile().ready is False` via `list_action_required()`) red forever: `QUARANTINED` is terminal with no valid transition (`_VALID_TRANSITIONS` in `service/placement_intents.py`), and no endpoint releases a classic-DCA intent — the only escape is manual SQLite surgery. Only accumulation orders have a repair path (`POST /accumulation/repair`, `service/accumulation/repair.py`, served in the accumulation `_repair_only()` mode). Add a mode-neutral recovery affordance for classic-DCA quarantined intents, e.g. extend repair-only mode to them and expose a lookup-only endpoint that (a) reconciles the quarantined order under the currently configured credentials and applies terminal evidence through the existing `PlacementRecoveryHandler.resume` path, or (b) records an explicit operator dismissal into a non-blocking terminal disposition after review.

**Why:** The startup error "Exchange placement reconciliation requires operator action before trading can start: \<operation_id\>" names an operator action that does not exist for classic-DCA intents. Any quarantine cause (legacy unscoped `accepted`/`filled` intent surviving a pre-`075fe4f` upgrade, `local_recovery_failed`, `exchange_lookup_unavailable`, account-scope change, `limit_order_missing_id`) can end in a permanent lockout; the 2026-11-07 startup fix only completes legacy unscoped `persisted` intents (no exchange I/O), so the remaining states still have no exit.

**Context:** 2026-11-07 investigation of the reported startup lockout (a `limit_sell` intent quarantined at startup after upgrading to the latest main). The scope gate added in `075fe4f` (2026-10-24) quarantines every nonterminal intent whose `request_json` lacks `_execution_scope`; legacy `persisted` intents now complete before the gate (regression test `test_legacy_unscoped_persisted_intent_completes_without_lookup`), while I/O-requiring legacy states stay quarantined as codified by `test_legacy_unscoped_result_stays_unresolved_without_invented_binding` and the runtime dedup guard `test_workflow_does_not_complete_unscoped_saved_result`.

**Depends on:** The startup gate and `AccumulationRepairOnlyMiddleware` in `app.py`; the accumulation repair flow is the reference pattern. The completed backup-classification entry (2026-11-08) left a follow-up here: point its `quarantined_intents` finding's `next_action` copy at this repair endpoint once it ships.

**Priority:** P2

### Upgrade to Litestar 3.x and pandas 4.x after release

**Status:** Recorded 2026-11-07 as the follow-up of the completed "Prepare
request bodies and OHLCV helpers for future major upgrades" entry. Neither
major is released yet (litestar 2.25.0 and pandas 3.1.1 are current as of
2026-11-07); start each only once upstream releases it. Second prep step
landed 2026-11-07: all three custom ASGI middlewares
(`AccumulationRepairOnlyMiddleware` in `app.py`,
`TrustedLanHttpMiddleware`/`WebSocketOriginMiddleware` in
`service/origin_policy.py`) now subclass `litestar.middleware.ASGIMiddleware`
(the protocol litestar 3.0 requires: `handle(scope, receive, send, next_app)`,
no `app` in the constructor, registered as direct instances) and no
`DefineMiddleware` usage remains; verified working on 2.25.0 with full CI
green.

**What:** Upgrade the two held major-version Python dependencies in dedicated,
separately tested changesets:
- `litestar` 2.25.0 -> 3.x (implicit reserved-kwarg body inference is removed
  in 3.0; the prep wave already marks all ten body parameters with
  `JSONBody[...]` and the middlewares already use the 3.0 `ASGIMiddleware`
  protocol, so the bump is expected to be validation of both plus the
  `litestar[testing]` extra for the TestClient and full-suite re-verification
  under the new major).
- `pandas` 3.1.1 -> 4.x (PDEP-8 `inplace` keyword removal; the prep wave
  already replaces all seven `inplace=True` calls in
  `backend/service/data_ohlcv.py` with explicit reassignments).

**Why:** The prep wave is complete, but the upgrades themselves must not ride
along: each is a major with its own compatibility review, and neither appears
in `pip list --outdated` until it releases, so this entry is their backlog
home.

**Constraints:** No bundling into a lock refresh — each upgrade ships as its
own changeset with the full backend CI green. The no-warning guard tests
(app-creation Litestar guard, `Pandas4Warning` helper guard) must stay green;
if pandas 4.0 renames or splits `Pandas4Warning`, update the guard's category
match within the same changeset.

**Depends on:** Upstream releases of litestar 3.x and pandas 4.x. The prep
entry's plan of record carries the re-verification checklist.

**Priority:** P2

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

### Classify backups before restore confirmation

**Status:** Completed 2026-11-08, implemented per the 2026-11-08 re-plan: a
read-only classification preview over the restore's own validation primitives,
a pre-confirmation review surface in the dashboard, and no force-restore path.
Origin: deferred owner decision from the May 2026 trade-modes-reset CEO plan
(recorded 2026-11-01 as D12=A; the original deferral to TODOS.md had never
been written).

**What shipped:**
- `POST /config/backup/classify` (`backend/controller/config.py`, strict
  `msgspec.Struct` body, no DB access, no lock, no confirm flag): runs the
  restore's validation primitives as a collect-all pass and returns a
  `classification` summary (`schema_version`, `trade_mode_era` =
  `accumulation` / `dynamic_dca` / `legacy_unspecified`,
  `pre_4_9_bridge_keys`, `includes_accumulation`) plus `findings` ordered
  blocking-first, each with `code`, `severity` (`info` / `warning` /
  `blocking`), `message`, safe-field `detail`, and optional `next_action`.
  `warning` findings name the silent outcomes (pre-4.9 bridge keys dropped per
  D11, row values whose columns no longer exist — including the sidestep-era
  waiting-state set — quarantined intent count, config-only pin removal);
  `blocking` findings mirror the existing restore refusals verbatim.
- `backend/service/backup_vintage.py` owns the shared residue vocabulary
  (`SIDESTEP_WAITING_STATE_COLUMNS`, `campaign_residue_rows`,
  `campaign_residue_symbols`); the restore's campaign-residue assertion now
  uses the shared predicate and the startup gate in `database.py`
  cross-references it, giving the "keep in sync" note of the residue-gate
  TODO one canonical definition.
- Dashboard: on restore-button click the composable fetches the
  classification for that mode (per-mode cache, in-flight dedupe) and
  `ConfigBackupRestoreControls.vue` renders the findings in an ARIA live
  region before the confirmation dialog. A blocking finding disables the
  matching restore button and the composable returns `blocked` before any
  confirm — no force-restore path. If the preview is unavailable the flow
  degrades to a warning and the restore endpoint's own checks remain the
  authoritative gate. The control-center wrapper announces blocked outcomes
  through the same live region.
- Zero restore behavior change: the D11 bridge-key drop, the residue gate,
  dry-run forcing, and the existing refusal messages are unchanged, and the
  existing restore suite passes unmodified. New backend fixture tests
  (`backend/tests/test_backup_classify.py`) pin every finding code, era
  variant, and the non-mutation guarantee; the frontend adds
  `tests-vitest/backup-classification.test.ts` and ratchets
  `useConfigBackupRestore.ts` into the vitest coverage guard.
- Docs: the endpoint contract in `docs/api.md`, the review semantics and the
  no-force-restore statement in `docs/operations.md` "Backup And Restore",
  and the 6.4.0.0 changelog entry.

**Follow-up:** Once "Add an operator repair path for quarantined classic-DCA
placement intents" ships, point the `quarantined_intents` finding's
`next_action` copy at that repair endpoint (copy update ships in that
changeset).

**Plan of record:** `~/.gstack/projects/TBMoonwalker-moonwalker/backup-classification-replan-20261108.md`

**Effort:** M

**Priority:** P3

### Decide the migration-ledger prune policy (Phase 5 ledger hygiene)

**Status:** Completed 2026-11-08. Policy decided as D1=B (collapse + full
prune, "Shape B" of the plan): a gated, checksum-safe ledger-hygiene prune
plus the `015`↔`003` collapse, with the pruned definitions kept in the code
and a runner retire rule that keeps a prune from being undone.

**What shipped:**
- `2026-11-09-024-ledger-hygiene-prune` (data step,
  `backend/service/database.py`): on an install that carries the MSV floor
  marker, deletes every `schema_migrations` row whose version sorts older
  than the prune version plus the inert
  `2026-09-sidestep-removal-v1` `config_migrations` row. The floor marker
  and the live signal-settings row are never pruned; a pre-floor install
  (no marker) keeps its full history. One transaction, idempotent, resumable
  through an interrupted run.
- The runner in `backend/service/schema_migrations.py` gained the retire
  rule: on a pruned database it skips a definition only when its row is
  *missing*, its version is older than the prune, and the prune row is
  durably `applied` — so the pruned definitions (kept so unsupported
  installs crossing the floor from below still migrate) never re-create
  their rows, and rows that exist (including a failed one) still retry under
  the unchanged checksum gate.
- The `015` (`2026-10-23-015-accumulation-dust-archive`) definition — a
  no-op repeat of 003's `_ensure_trade_ledger_columns` — is removed; its
  ledger row dies in the prune.
- Tests: retire-rule semantics (missing retired rows skip, existing failed
  rows retry, newer versions migrate), prune gate (pre-floor install keeps
  full history), prune-at-floor (deletes once, stays put, keeps live config
  rows), interrupted-prune resume, fresh-install end-state (pruned on first
  boot, stable on the second), preflight invariance on a pruned ledger, and
  the updated 4.9-fixture resume expectation (pruned terminal ledger, floor
  marker kept).
- Durable policy recorded in `docs/operations.md` ("Migration ledger
  retention") and `docs/development.md`; CHANGELOG entry for the next
  release.

**Plan of record:**
`~/.gstack/projects/TBMoonwalker-moonwalker/migration-ledger-prune-policy-plan-20261108.md`
(D1=B, 2026-11-08).

**Effort:** M

**Priority:** P3

### Remove the three deferred Phase 4 data-compat shims at their concrete floors

**Status:** Completed 2026-11-07 by owner decision: the MSV floor was raised
from 4.9.0.0 to 6.3.0.0 (option B of D8, explicitly re-decided), which passes
all three recorded floors at once.

**What shipped:**
- The floor is now `6.3.0.0` in `backend/service/msv.py` (marker row
  `2026-11-msv-floor-6-3-v1` in the `config_migrations` ledger); the preflight,
  `GET /monitoring/msv`, `docs/operations.md` and `docs/monitoring.md` follow
  the constant. `record_msv_floor_marker` now marks an existing install on its
  first at-floor startup — after the preflight fires the one-time pre-floor
  warning — so a skip-install no longer reports `unsupported` forever with
  unsatisfiable guidance. A fresh database carrying pre-floor legacy bridge
  keys (a restored pre-floor backup) stays unmarked and keeps reporting
  `unsupported`.
- The CSV fee-provenance fallback in `has_fee_inclusive_cost`
  (`backend/service/trade_math.py`) is gone: provenance is explicit-only and a
  missing `cost_includes_fees` flag behaves like an explicit False (legacy fee
  estimation). Recorded floor >=5.3.0.0 (016 provenance, 04b6990) passed.
- The four-column accumulation CSV declaration format
  (`backend/service/accumulation/imports.py`) is rejected with an explicit
  error for fresh uploads and persisted legacy declarations; the fee-aware
  format is required. `docs/accumulation.md`,
  `docs/howto-operate-accumulation.md`, `docs/signals.md` and the dashboard
  placeholders were updated. The classic Dynamic DCA CSV import keeps its
  four-column format.
- `legacy_accumulation_graph` (the `backend/service/shared_accumulation.py`
  editor view) is removed: `get_strategy_detail` no longer wraps legacy-shape
  accumulation documents, the `legacy_accumulation_view` metadata plumbing is
  gone, and duplicating a legacy preset is rejected with a clear error. Legacy
  documents remain fully parseable by the accumulation runtime and catalog
  (`parse_accumulation_strategy_document` keeps both shapes), and
  `regime_accumulation_graph` now builds its base shape directly.

**Operator-visible consequences (documented in `docs/operations.md` and the
6.3.0.0 changelog):** pre-floor trade rows without a provenance flag lose the
inferred fee-inclusive cost; pre-floor four-column accumulation declarations
can no longer be imported or revalidated; legacy-shape preset documents are
no longer rendered or duplicable in the strategy builder.

**Plan of record:** `~/.gstack/projects/TBMoonwalker-moonwalker/legacy-migration-removal-plan-20261101.md`
(D8=A deferral; superseded by the owner's explicit re-decision on 2026-11-07).

**Effort:** M

**Priority:** P3

### Add the recovery DCA status card to the vitest coverage guard

**Status:** Completed 2026-11-07. The card is now ratcheted into the vitest
coverage guard and its pre-card surface labels are asserted on the card
itself.

**What shipped:**
- `src/components/RecoveryDcaStatus.vue` added to `coverage.include` in
  `frontend/vitest.config.mts` (this entry named the config
  `vitest.config.ts`; the file has since been renamed to `.mts`) with a
  per-file threshold ratcheted at 90/80/95/90 (stmts/branches/funcs/lines)
  against the measured 92.47/84.74/96.15/91.78. The uncovered remainder is
  the `insufficient_tp_improvement` and `invalid_trade_state` /
  `target_not_solvable` warning branches.
- New surface test in
  `frontend/tests-vitest/recovery-dca-status.test.ts` re-asserting the five
  labels the old `recoveryDcaSurface.test.cjs` guard checked on
  `OpenTradeExpandedRow.vue` before the v4.15.0.0 card split, in their
  post-split form: the `Recovery DCA status` aria-label, `Trigger ≤ USDC`,
  `reference ATR`, `SO 1 / 5`, and the `Projected TP 0.25` sizing line.
  The CJS guard keeps its single delegation assertion.

### Prepare request bodies and OHLCV helpers for future major upgrades

**Status:** Completed 2026-11-07. Litestar 2.25.0 and pandas 3.1.x no longer
expose the deprecation warnings this entry named: all ten unmarked `data`
body parameters are `JSONBody[...]`-marked and all seven `inplace=True` calls
in `backend/service/data_ohlcv.py` are explicit reassignments. No warnings
were suppressed (no CI filter changes) and no dependency versions changed;
the future majors are tracked by the "Upgrade to Litestar 3.x and pandas 4.x
after release" entry in Next up.

**What shipped:**
- `JSONBody[...]` on all ten unmarked `data` parameters:
  `backend/controller/backtest.py` (run_backtest),
  `backend/controller/config.py` (activate_live_trading, pause_trading,
  resume_trading, deny_symbol, restore_backup), `backend/controller/
  strategies.py` (duplicate/create/validate/save). Strict payload validation
  preserved: the msgspec.Struct DTOs keep `forbid_unknown_fields`, the dict
  handlers keep app-level validation, and the existing malformed/unknown-field
  regression tests pass unmodified.
- Explicit reassignment at all seven deprecated call sites in
  `backend/service/data_ohlcv.py` (`rows_to_dataframe`,
  `serialize_ohlcv_dataframe`, `resample_ohlcv_data`); candle timestamps,
  resampling, duplicate removal and history serialization verified by the
  existing suite plus new regression tests.
- New regression guards: an app-creation test asserting no Litestar
  "Reserved kwarg" deprecation for the three controllers; a helper test
  asserting no `pandas.errors.Pandas4Warning` (matched by category); a
  duplicate-removal first-wins test; a partial-candle sanitization test (a
  lost `rows_to_dataframe` dropna corrupts resampled bucket values that no
  other test catches — probe-verified 2026-11-07); HTTP-boundary TestClient
  cases for the changed dict handlers (malformed JSON / non-object body ->
  400, path+body binding on PUT /strategies/{slug}).

**Plan of record:** `~/.gstack/projects/TBMoonwalker-moonwalker/fixed-todos-eng-review-20261107-105742.md`

**Effort:** M

**Priority:** P2

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
