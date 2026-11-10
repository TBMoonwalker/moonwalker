# TODOS

## Next up

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

### Upgrade frontend major dependency: TypeScript 7

**Status:** jsdom 31.0.0 and @types/node 26.6.6 shipped 2026-11-08 (see
"Upgrade the vitest jsdom environment to 31" and "Move the frontend Node
types to the Node 26 line" in Completed). TypeScript 7 remains blocked on
tooling (2026-11-08 compatibility review, owner decision 2026-11-08:
hold). Original 2026-11-06 hold list of the 2026-11-06 frontend dependency
hygiene pass (patch/minor wave applied the same day: axios 1.21.0, vite
8.3.6, vitest 5.1.0, vue 3.5.45, vue-tsc 3.3.14, @playwright/test 1.65.0,
knip 6.44.1).

**What:** Bump the remaining held major-version frontend dev dependency in
a dedicated, separately tested changeset:
- `typescript` 6.0.3 -> 7.0.2 (blocked until Volar supports 7: TypeScript
  7.0 ships no programmatic compiler API — the `typescript` package's main
  entry exports only `version`/`versionMajorMinor` — and `vue-tsc` 3.3.14
  crashes on it with `ERR_PACKAGE_PATH_NOT_EXPORTED: './lib/tsc'`, while
  its `@vue/language-core` 3.3.14 peer-declares `typescript: <7` and no
  newer vue-tsc release exists; the 2026-11-06 TypeScript 7.1 beta
  restores the compiler API and makes Vue first-class, so revisit together
  with a TS 7.1 stable release plus a vue-tsc that accepts it).

**Why:** Recorded rather than bundled: major bumps need the compatibility
review the dependency hygiene policy requires, and the axios 1.21.0 wave
proved the test suite is the right gate for behavior changes (its
header-default recognition change passed clean). The jsdom 31 wave
confirmed it: the full frontend CI passed unmodified, and the typescript
7.0.2 blocker was found by the review rather than by a broken build.

**Priority:** P3

### Upgrade Python major dependency: multidict 7

**Status:** Recorded 2026-11-07 as the hold list of the 2026-11-07 Python dependency hygiene pass (patch/minor wave applied the same day: ccxt 4.5.92, cachetools 7.3.0, pandas 3.1.1, python-socketio 5.18.1, websockets 17.4, ta-lib 0.8.3, anyio 4.16.0, click 8.5.1, mypy 2.4.1, pip 26.3, pytest 9.2.0, pytest-asyncio 1.4.1.post1, ruff 0.17.4, filelock 4.2.9). The companion `python-dateutil` 4.0.0 changeset shipped 2026-11-08 (see "Upgrade python-dateutil to 4.0.0" in Completed); this entry is the remaining, still-blocked half.

**What:** Bump the held major-version Python dependency in a dedicated, separately tested changeset:
- `multidict` 6.9.1 -> 7.2.1 (transitive of aiohttp, hard-pinned to `6.9.1` by ccxt, so the resolver cannot move it until a future ccxt release relaxes the pin; revisit together with the next ccxt release that permits multidict 7).

**Why:** Recorded rather than bundled: major bumps need the compatibility review the dependency hygiene policy requires, and multidict is additionally unresolvable today because of ccxt's hard pin. As of 2026-11-08 the latest ccxt (4.5.92) still pins `multidict==6.9.1`, while aiohttp 3.14.5 already permits `multidict<8.0,>=4.5`, so ccxt's exact pin is the sole blocker and must not be forced through an override. Note: idna stays at 3.18 for the same reason (ccxt 4.5.90-4.5.92 all hard-pin `idna==3.18`), so the idna 3.20 "outdated" row is expected to persist.

**Priority:** P3

## Control Center verification

### Verify remaining rendered accessibility observations

**Status:** Follow-up verification from the historical source audit; not a
claim that the current UI has these defects.

**What:** Check rendered dark-mode contrast, mobile pagination touch targets,
and the intentional scope of compact table typography against DESIGN.md.
The old theme-ownership concern is already addressed by the shared theme store.

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

### Repair the two consistently failing Playwright specs

**Status:** Completed 2026-11-10; `MOONWALKER_RUN_E2E=1` is green again
(49/49 across all five Playwright projects for the affected files).

**Root causes:** three distinct test-side races, none in the app code:
- `background-recovery.spec.ts:5`: the `**/orders/**` counter also counted
  the dashboard's new `GET /orders/placement-recovery` load from
  `PlacementRecoveryCard` (added after the spec was written). The mock now
  answers that path with an empty intent list and only counts
  order-mutation POSTs, which is what the no-order assertions guard.
- `accumulation.spec.ts:11`: the `expect(requests).toHaveLength(1)` after
  the confirm click was a synchronous check that always raced the route
  handler's push (earlier revisions had `await expect(...)` lines after the
  click that acted as the barrier and were removed with UI changes). The
  spec now waits for the panel's "Recorded outcome: applied" notice, which
  only renders after the mocked POST was handled.
- `accumulation.spec.ts:240` (previously the "flaky" one, ~20% on
  tablet/mobile chromium): `page.reload()` could outrun the route handler
  for the intentionally aborted first POST, so the mock counted the retry
  as the first POST and aborted it as well. The spec now polls
  `requests.length === 1` before reloading.

**Note:** the firefox/webkit projects need `npx playwright install`
(browser builds are not on every machine); once installed, all projects
pass.

### Review stale full-form saves against concurrent denylist appends

**Status:** Completed 2026-11-10 as commit `40eb50a` on `fixed-todos`;
the server-side revision check was already implemented and is now verified
end to end by regression tests and a two-client E2E spec.

**What:** Verified that a deny append advances the config revision in the same
transaction as its write, so a full config save based on an older generation is
rejected with HTTP 409 and the newer deny survives; the dashboard shows a
stale-configuration banner and the operator reloads and re-applies edits.
Intentional token removal remains possible through a freshly loaded form
(whole-list replacement). The deny endpoint returns the advanced
`config_revision`, and the open-trades deny action broadcasts a `deny`
invalidation so other tabs notice immediately. Regression coverage:
`backend/tests/test_denylist_append.py`
(`test_stale_full_form_save_cannot_lose_concurrent_deny`),
`backend/tests/test_denylist_deny_endpoint.py`, and the two-client E2E flow
in `frontend/tests-e2e/control-center.spec.ts`
("a deny append rejects the stale form save until the operator reloads").

**Decision:** Keep the revision check as the only conflict mechanism; no
per-field merge on 409. Re-applying unsaved draft edits onto a fresh snapshot
after a rejected save is deferred as a UX enhancement.

**Design:** [Denylist semantics](docs/designs/denylist-symbol-from-open-trade.md).

### Evaluate server caching and incremental timeline loading

**Status:** Completed 2026-11-09 as three CI-green code commits on
`fixed-todos` (perf, tests, harness) plus the docs commit. Follow-up
P1.5 (2026-11-10) then made the cold rebuild itself cheap, so a reload no
longer stalls — see below.

**Plan of record:**
`~/.gstack/projects/TBMoonwalker-moonwalker/timeline-server-cache-plan-20261109.md`

**What was measured:** the new `scripts/benchmark_timeline.py` harness
seeds throwaway databases at the real 60-second snapshot density
(16 d / ~23k rows like the current live instance, 1 y / ~525k rows steady
state, 2 y / ~1.05M rows) plus a `sqlite3` backup copy of the live
database, and runs sequential, 4/8/16-concurrent, and 16-client burst
scenarios. At the steady-state 1-year size the uncached endpoint resampled
on every fetch: p50 4.4 s per fetch, and 16 concurrent clients queued 16
resamples with p50 32.1 s / p95 64.8 s per fetch. The response payload was
already bounded (206 points, ~17.7 KB JSON), so the cost was server CPU and
SQLite I/O, not bandwidth.

**What shipped:**
- `Statistic.get_profit_overall_timeline` caches the resampled timeline for
  one snapshot interval (60 s): single-flight rebuild (lock plus
  double-checked expiry), immutable cached value returned as a per-fetch
  list copy, and query errors left uncached.
- Every `UpnlHistory` write invalidates the cache process-wide: snapshot
  writes happen in `_get_profit_base` from the controller graph, the DCA
  engine, and the signal plugins (each its own `Statistic` instance), so a
  shared data generation advances on any write and the next fetch reflects
  the new bucket immediately.
- Retention cleanup fires a new `Housekeeper.on_upnl_history_changed`
  hook, wired by `app.py` to `statistic.invalidate_timeline_cache`.
- The endpoint's path, arguments, response shape, and the per-request 409
  unverified-valuation guard are unchanged; disconnect recovery is
  unchanged (stateless endpoint; the client store already treats a failed
  refresh as unverified and retries).
- After the cache: the same scenarios resample once per window (16→1 and
  32→1 resamples; warm fetches are sub-millisecond cache hits) and the
  worst concurrent wait drops from 64.8 s to 5.9 s. Full before/after
  reports: `~/.gstack/projects/TBMoonwalker-moonwalker/benchmark-reports/`
  (`2026-11-09T191632Z-timeline-server.json` before,
  `2026-11-09T192949Z-timeline-server.json` after).

**Follow-up (2026-11-10, P1.5 — cheap rebuild):** the live check above
proved the cache, but a single client's reload (or standby→active switch)
still hit the expired TTL and triggered one full rebuild: ~6.4 s on the
370k-row deployment database, and — because the worker-thread pandas
resample held the GIL — every concurrent boot request stalled behind it
(`/config/all` and `/accumulation/strategies` measured ~6.2 s on the
reloaded page). The rebuild now computes the adaptive bucket grid in
Python and resolves every bucket with one indexed `LIMIT 1` seek on the
snapshot timestamp (`Statistic._fetch_profit_overall_timeline`), reading
~220 rows instead of the full year of snapshots; it runs natively on the
event loop, so no worker-thread GIL starvation remains. The output is
point-for-point identical to the old full-resample path: the pandas
pipeline is kept in `backend/tests/test_statistic_timeline_prewin.py` as a
differential oracle (adversarial bucket/slice boundaries, sub-second and
identical-timestamp duplicates, week-straddle label collisions, unverified
rows, sparse and empty fixtures, a full year of 60-second snapshots with
every bucket of every slice filled, aligned and sub-second-offset rebuild
times). Cold rebuild at 1-year scale (525k rows): 2.9–5.9 s → ≤38 ms; at
2-year scale (1.05M rows): ≤70 ms; concurrent-16 worst wait: 5.9 s →
38 ms (`2026-11-10T141830Z-timeline-server.json`). The benchmark harness
had been seeding `T`-separated timestamp strings (`isoformat`) that never
occur in production storage, which the lexicographic bucket bounds read
wrongly; the seed now writes the production format (space separator,
`+00:00`), and the corrected runs restore the expected point counts
(144/205/205 vs the pre-change 144/206/205). Endpoint contract, 409
guard, and cache semantics are unchanged.

**Decision:** the proposed P2 incremental delta cursor is not justified
(measurement evidence in the design doc) — no cursor state and no second
response shape; the no-argument endpoint remains the sole contract. P3
(configurable snapshot cadence) remains a proposal in
[Dashboard history loading](docs/designs/delta-loading.md). Open trades
remain full-state and closed history remains paginated.

**Verification:** 10 new unit tests in
`backend/tests/test_statistic_timeline_cache.py` (cache hit, per-fetch
copy, same- and cross-instance write invalidation, TTL expiry,
single-flight, retention hook with and without deletions, uncached query
errors, cached/fresh-build equality) plus the endpoint and startup suites;
full CI green (`cd scripts && ./ci.sh`) — 2,292 backend tests, 374
frontend tests, type checks, lint, and coverage floors. No API, config, or
schema change. Live-instance check 2026-11-10 against the running
deployment (http://192.168.6.5:8160): cold fetch ~6 s vs cached fetches
~0.1–0.5 s; 16 concurrent fetches all served in <0.7 s (one rebuild, not
16); with the bot flat, a profit-WebSocket connection (dashboard-client
behavior) drove the 60-second snapshot gate, and the new snapshot value
appeared on the next timeline fetch inside the previous build's TTL window
— write invalidation observed, bucket updates confirmed. Retention-cleanup
invalidation is unit-verified (24-hour housekeeper cycle, not triggerable
on demand). The check also surfaced an environmental observation, not a
defect in this change: the deployment host's clock appears ~1 hour behind
this machine (stored row timestamps lag wall-clock fetch times by
~48–63 minutes), so its NTP configuration is worth a look. The P1.5
follow-up's reload scenario still needs a live re-check on that deployment
(cold reload should drop from ~6 s to well under 1 s, and the concurrent
boot requests should no longer stall) once the host picks up this code;
the differential tests and benchmark above are the stand-in evidence.

**Priority:** P3

### Remove the service/orders.py compatibility facade

**Status:** Completed 2026-11-09 as three CI-green code commits on
`fixed-todos` (`dc9f29c`, `3b2b02f`, `950f680`) plus the docs commit.

**Plan of record:** `~/.gstack/projects/TBMoonwalker-moonwalker/orders-facade-removal-plan-20261109.md`
(decisions R1–R9; the scoped correctness check is recorded in the plan).

**What shipped:**
- `service/orders.py` is deleted. Its mode-neutral seams moved to the
  service-root module `service/placement_recovery_entry.py`
  (`PlacementRecoveryEntry`): it receives a caller-constructed
  `DcaOrderLifecycle` (app.py owns both constructions), owns the
  `accumulation_recovery` seam and the startup entry point
  `reconcile_placement_intents` (which reads the seam at
  reconciler-construction time, D6 unchanged), builds the operator
  placement-repair service over the shared recovery resume handler, and
  wires the bybit reconciler factory. The DCA recovery-handler callback
  wiring is owned once, on `DcaOrderLifecycle.build_recovery_handler()`.
- Consumers re-pointed: `app.py` replaces `runtime_state.placement_orders`
  with `order_lifecycle` + `placement_recovery`; the runtime service graph
  carries `order_lifecycle` and receives the entry
  (`build_runtime_services(placement_recovery=…)`);
  `TradingControlsService` takes `order_lifecycle`; the orders controller
  proxy resolves the `"order_lifecycle"` graph field; the three signal
  plugins self-wire `DcaOrderLifecycle()`.
- 20 test files re-pointed at `DcaOrderLifecycle` (the facade's `.dca` hop
  collapses onto the lifecycle); the facade-specific split guards are
  retired and the D6 late-seam guard re-homes in
  `backend/tests/test_placement_recovery_entry.py` with the
  entry-composition, finally-close, and repair-wiring units.
- Coverage ratchet: the `service/orders.py` row is replaced by the
  `placement_recovery_entry.py` row at the measured 100.0 branch
  coverage; the split rows are flat or better (lifecycle 73.0 → 73.1,
  finalization 69.6, routing 90.0, runtime_services 75.0 → 78.6).

**Verification:** full CI green (`cd scripts && ./ci.sh`) — 2,282 backend
tests, type checks, lint, and coverage floors. No API, config, schema, or
log-message changes.

**Priority:** P3

### Make logger handler de-duplication robust to uncanonical log directories

**Status:** Completed 2026-11-09 as one changeset on `fixed-todos`, CI-green.

**Plan of record:** `~/.gstack/projects/TBMoonwalker-moonwalker/logger-handler-dedup-robustness-plan-20261109.md`

**What shipped:**
- `backend/helper/logger.py`: `_resolve_log_path` now canonicalizes in both
  branches (`Path(...).resolve()`), and a new `_canonical_log_file()`
  (`os.path.realpath`) canonicalizes both sides of the handler de-duplication,
  so one (logger name, log file) pair never receives two file handlers when
  `LOG_DIR` sits behind a symlink (macOS `/var` -> `/private/var`), carries
  `..`/`.` components, or is an un-normalized absolute path. `__create_logger`
  checks de-dup *before* creating the handler, so a redundant call no longer
  opens and discards a file handle, and Windows no longer creates a discarded
  second handler.
- `backend/tests/conftest.py`: the temp log dir is anchored with
  `_LOG_TMP.resolve()`, so the redirected `LOG_DIR` is canonical and
  `_close_temp_log_handlers`' `startswith` match on each handler's
  `baseFilename` works.
- Tests: `backend/tests/test_logger_factory.py` gains five focused cases
  (repeated-call de-dup, symlinked `LOG_DIR` de-dup + canonical
  `baseFilename`, absolute-symlink path, distinct-files-not-collapsed,
  not-yet-existing file);
  `backend/tests/test_orders_split_guards.py::test_new_modules_route_logs_to_shared_dca_logger`
  now asserts the shared `dca` logger owns exactly one `dca.log` handler.

**Priority:** P3

### Add an operator repair path for quarantined classic-DCA placement intents

**Status:** Completed 2026-11-09. Recorded 2026-11-07 during investigation of
a reported startup lockout after upgrading to the latest main: a
`limit_sell` intent quarantined at startup (most likely
`reconciliation_account_scope_unverified` on a legacy unscoped intent) had
no operator exit, so the instance crashed on every boot with "Exchange
placement reconciliation requires operator action before trading can start".
The 2026-11-07 same-day fix removed the most common trigger (legacy unscoped
`persisted` intents now complete before the gate); this entry closed the
remaining operator-exit gap.

**What shipped:**
- Repair-only startup mode now covers quarantined classic-DCA intents: when
  reconciliation reports `ready is False` with action-required work and no
  other nonterminal work (`PlacementReconciliationSummary.remaining == 0`),
  `app.py` serves recovery instead of exiting. The accumulation branch keeps
  precedence; any remaining nonterminal work still fails closed.
  `AccumulationRepairOnlyMiddleware` became `RecoveryOnlyMiddleware` and
  gates both modes (recovery reads + `POST /accumulation/repair` +
  `POST /orders/placement-recovery/{id}/repair|dismiss` allowed; websockets
  closed with 1013; everything else 503/409 with `code: recovery_only`).
- `PlacementRepairService` (`backend/service/placement_repair.py`) with
  `list_quarantined()` / `repair()` / `dismiss()`. Repair is lookup-only:
  it resolves the order under the currently configured credentials and
  applies terminal evidence through the same `resume` handler startup
  reconciliation uses (`operator_repair_fill_resumed`,
  `operator_repair_open_limit_reattached`, `operator_repair_cancel_confirmed`,
  `operator_repair_identity_not_found`,
  `operator_repair_exchange_order_{state}`); inconclusive evidence leaves the
  intent quarantined. Dismissal records a terminal `rejected` disposition
  with reason code `operator_dismissed` and the operator's required note as
  the audit trail.
- The quarantine exit lives in
  `PlacementIntentService.release_quarantine()` (only
  `quarantined`/`restored_quarantined` → `completed`/`rejected`), so the
  sticky-quarantine invariant of `_VALID_TRANSITIONS` stays structural:
  normal transitions still cannot move a quarantined row.
- Endpoints in `backend/controller/orders.py`: `GET
  /orders/placement-recovery`, `POST
  /orders/placement-recovery/{operation_id}/repair`, `POST
  /orders/placement-recovery/{operation_id}/dismiss` (body
  `{"note": ...}` required). Errors: 404 `not_found`, 409 `conflict`
  (not-quarantined or accumulation-routed intents), 400 `invalid_request`.
- Dashboard: `PlacementRecoveryCard.vue` on the Trading overview lists every
  quarantined intent with Repair and note-gated Dismiss actions and a
  restart hint; it is fetch-based, so it works while websockets are closed in
  recovery mode. API client `api/placementRecovery.ts`, composable
  `usePlacementRecovery.ts`, types in `types/placementRecovery.ts`, vitest
  spec `tests-vitest/placement-recovery-card.test.ts` (9 tests) with the
  component and composable ratcheted into the coverage guard.
- Tests: `backend/tests/test_placement_repair.py` (24 tests: listing,
  release transitions, every repair evidence mapping, dismissal audit,
  conflict/not-found/invalid errors, accumulation routing, lookup-only
  guard), plus startup-mode and middleware-gate tests in
  `backend/tests/test_app_startup.py`.
- The backup-classification `quarantined_intents` finding's `next_action`
  copy now points at the Placement recovery card (its 2026-11-08 follow-up
  is resolved).
- Docs: `docs/operations.md` "Startup Recovery", `docs/api.md` Orders
  section, and the 6.4.0.0 changelog entry.

**Immediate-unlock procedure for a locked instance (before the fixed
build):** query `placement_intents` for the `operation_id` from the startup
error, inspect that order's state on the exchange under the configured
credentials, and only then either upgrade and use the card, or move the row
to a verified terminal state (`state`, `reason_code`, `error_message`,
`completed_at`) — see `docs/operations.md` "Startup Recovery".

**Priority:** P2

### Split service/orders.py into the dca/ package and a mode-neutral facade

**Status:** Completed 2026-11-09 as one changeset on `fixed-todos`
(commit `2583f1d`), CI-green per commit.

**Plan of record:** `~/.gstack/projects/TBMoonwalker-moonwalker/orders-split-dca-facade-plan-20261108.md`
(decisions D1–D6; outside-voice corrections OV1–OV4 applied).

**What shipped:**
- `service/orders.py` (2,591 lines) split into three modules plus a thin
  facade. `service/dca/finalization.py` owns the classic-DCA trade
  finalization (persist + stats + the two `MonitoringService.notify_trade`
  seams at former `orders.py:506`/`:644`, partial-sell handling, TP-limit
  payload building, entry-size retry, unsellable-state reset,
  order-status predicates) as 18 free functions behind an explicit
  `DcaFinalizationContext` built from the current collaborators at call
  time. `service/dca/order_lifecycle.py` owns the DCA execution lifecycle
  (`DcaOrderLifecycle`: buy/sell receipt, TP-limit arm/cancel/reconcile,
  stop signals, manual operations, durable placement-intent transitions).
  `service/order_routing.py` owns the mode-neutral lifecycle routing
  (`OrderLifecycleRouting`: the legacy-mutation ownership guard at former
  `orders.py:107-145`, snapshot-currency validation, trade-state loading,
  operator mutation results).
- `service/orders.py` is now a ~250-line compatibility facade (`Orders`)
  that composes the mode-neutral routing and the DCA lifecycle over the
  shared `build_default_order_collaborators()` wiring list. The
  mode-neutral startup reconciliation entry point (former `orders.py:320`)
  stays on the facade with the `accumulation_recovery` seam (former
  `orders.py:101`, wired in `app.py:213-215`), read at
  reconciler-construction time. `dca/engine.py` uses `DcaOrderLifecycle`
  directly; importing the new modules pulls in neither the root facade nor
  the engine, and the lazy `from service.dca import Dca` export is
  preserved.
- New structural guards (`backend/tests/test_orders_split_guards.py`):
  import invariant, facade shape, delegation parity, self-wiring parity,
  logger routing (both new `dca/` modules log through the shared `dca`
  logger to `logs/dca.log`), and the D6 post-construction
  accumulation-seam test; plus finalization leaf units
  (`backend/tests/test_dca_finalization.py`). 20 test files migrated (121
  reassignment/patch sites).
- Coverage ratchet: the `service/orders.py` row is replaced by rows for
  the three new modules plus the facade at the measured post-move branch
  coverage (finalization 69.6, lifecycle 73.0, routing 90.0, facade
  100.0), each at or above its pre-move per-group baseline (66.1 / 73.0 /
  90.0, measured at `ae272a8`).

**Verification:** full CI green (`cd scripts && ./ci.sh`) — 2,249 backend
tests, type checks, lint, and coverage floors.

**Priority:** P3

### Upgrade python-dateutil to 4.0.0

**Status:** Completed 2026-11-08 as the companion changeset of the "Upgrade Python major dependencies: multidict 7, python-dateutil 4" hold list; the still-blocked multidict 7 half remains in Next up.

**What shipped:**
- `python-dateutil` 3.0.0 -> 4.0.0 (exact pin in `backend/requirements.in`, regenerated in both hash locks via `scripts/compile_requirements.sh`). dateutil 4.0.0 (released 2026-11-01) requires Python >=3.11 and drops the `six` dependency; it retains the 3.0.0 `tz.tzfile` rewrite, so the "post-2038 TZif support" rationale behind the pin still holds. The only behavior change is a stricter `parser.isoparse` (numeric fields must carry exactly the expected number of digits), which Moonwalker does not exercise — its sole dateutil usage is `dateutil.tz.gettz` in `backend/service/data_ohlcv.py`. The now-orphaned `six` 1.17.0 transitive (pulled in only by dateutil) is dropped from both locks; `tzdata` is retained because dateutil 4.0.0 still depends on it. No other package version changed in either lock.
- Compatibility review: pandas 3.1.1 (released 2026-11-04, after dateutil 4.0.0) declares `python-dateutil>=2.9.0` with no upper bound and ships an explicit dateutil>=3.0 compatibility fix for timezones such as `dateutil/US/Pacific` (GH 71459); litestar 2.25.0 and tortoise-orm 1.1.9 declare no dateutil dependency and do not import it at runtime.
- Security/provenance: the 4.0.0 wheel and sdist carry full PyPI provenance and a verified Sigstore publish attestation from the genuine `github.com/dateutil/dateutil` release workflow; OSV and the PyPI security panel report no vulnerabilities for the version.
- Verification: full CI green — 2,230 backend tests plus the full frontend suite, type checks, lint, builds, coverage gates, both vulnerability audits and registry-signature checks. The two timezone regression tests in `backend/tests/test_data_ohlcv_serialization.py` (repeated autumn hour, summer after 2038) pass unchanged under 4.0.0.

**Priority:** P3

### Extend the campaign residue gate to the full 021 drop set

**Status:** Dropped 2026-11-08 by owner decision: the 4.8.x compatibility
scenario that motivated this hardening is no longer needed, so the gate's
current scope (campaign references only) is final. No code change; the
startup and restore gates keep their current assertions and their
documented "keep in sync" behavior.

**What it covered:** The campaign-residue gate (startup
`_assert_no_open_trade_campaign_residue` in `backend/service/database.py`
and restore `_assert_no_open_trade_campaign_residue` in
`backend/service/backup_restore.py`) aborts startup / refuses a restore
only when an `opentrades` row carries `campaign_id IS NOT NULL`. The seven
sidestep-era waiting-state columns that migration 021 drops
(`waiting_reference_price`, `reserved_reentry_quote`,
`waiting_reference_amount`, `waiting_reference_quote`,
`virtual_waiting_profit`, `virtual_waiting_profit_percent`,
`last_transition_at`) are zeroed silently on rows that still carry them;
the entry proposed extending the assertion to the full drop set (campaign
reference OR non-zero waiting state) with a fixture test.

**Why dropped:** In 4.8.x the waiting-state writers were campaign-context
paths that propagated `campaign_id`, so the flagged scenario needed an
already-inconsistent row on an unsupported 4.8.x direct upgrade. With the
4.8.x compatibility no longer needed, the residual risk does not justify
extending the gate.

**Origin:** Pre-landing review of
`chore/hygiene-logging-serialization-sync-2026-10` (2026-11-02), finding
F5; recorded rather than extended that wave (operator decision
2026-11-02).

**Priority:** P3

### Move the frontend Node types to the Node 26 line

**Status:** Completed 2026-11-08 as the second changeset of the Node 24 ->
26 migration, after the runtime floor itself moved in the companion
"chore(runtime): move the Node floor from 24 to 26 LTS" changeset.

**What shipped:**
- `@types/node` 24.19.2 -> 26.6.6 (exact devDep pin) and
  `@tsconfig/node24` 24.0.5 -> `@tsconfig/node26` 26.0.1;
  `frontend/tsconfig.node.json` now extends the Node 26 base (target/lib
  es2024 -> es2025, `ESNext.Temporal` added). The Node type package now
  describes the runtime the project actually runs.
- Security review: @types/node 26.6.6 is the genuine DefinitelyTyped
  scoped package (the 2024 typosquat campaign targeted the lookalike
  `types-node` name, not this one), has no known vulnerabilities or
  tampering findings, and passes the npm audit and registry-signature
  gates; @tsconfig/node26 is a config-only package whose full content was
  read from the registry tarball.
- Verification: full frontend CI green under Node 26.13.0 — vue-tsc
  type-check (the gate exercising the new typings), 364 vitest + 384
  legacy tests, coverage ratchet, build, vulnerability audit, signatures.

**Priority:** P3

### Upgrade the vitest jsdom environment to 31

**Status:** Completed 2026-11-08 as the first changeset of the "Upgrade
frontend major dependencies: jsdom 31, TypeScript 7, @types/node 26" hold
list.

**What shipped:**
- `jsdom` 30.1.3 -> 31.0.0 in `frontend/package.json` (exact devDep pin).
  jsdom 31 replaces its CSS engine with an integrated implementation (the
  @asamuzakjp and @csstools packages drop out of the tree), switches the
  optional canvas backend from `canvas` to `@napi-rs/canvas` (we install
  no canvas backend, so this is inert), and pauses HTML/XML parsing at
  blocking scripts.
- The `whatwg-url` override moved 17.2.0 -> 17.3.0, the attested version
  inside jsdom 31's declared `^17.3.0` range (17.3.0 only syncs the
  `search` setter with `searchParams` after stripping ASCII tabs and
  newlines, per whatwg/url@fde3f74); the npm audit signatures gate stays
  green.
- Verification: full frontend CI green — 364 vitest tests across 50 files
  and 384 legacy CJS tests unmodified, coverage ratchet, vue-tsc
  type-check, vite build, `npm audit --audit-level=high` (0
  vulnerabilities) and `npm audit signatures`.

**Priority:** P3

### Show an unavailable notice on replay charts without indicator series

**Status:** Completed 2026-11-08 per
`~/.gstack/projects/TBMoonwalker-moonwalker/replay-indicator-notice-plan-20261108.md`.
Origin: declined option of D19 (2026-11-01 legacy-migration-removal design
review), tracked per D22/R10.

**What shipped:**
- `frontend/src/components/TradeReplayChart.vue` now tracks an
  `indicatorUnavailable` state and shows a muted
  "Indicator overlays unavailable for this trade." caption (12px,
  `role="status"`) inside the chart stack whenever the indicator fetch yields
  no series — legacy rows without a deal id, empty indicator results, or
  failed indicator requests. The state is settled before the chart first
  paints (no flash), and the empty-candle message remains the only state when
  no candles exist.
- The previously swallowed indicator-fetch failure now also reports
  `console.warn` with the fetch error (UI stays muted); no backend or
  endpoint changes.
- New vitest spec `frontend/tests-vitest/trade-replay-indicator-notice.test.ts`
  covering all five states (empty result, fetch failure, missing deal id,
  series present, no candles).

**Priority:** P3

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

**Follow-up:** Resolved 2026-11-09 with the completed "Add an operator repair
path for quarantined classic-DCA placement intents" entry: the
`quarantined_intents` finding's `next_action` copy now points at the
dashboard's Placement recovery card.

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
