# TODOS

## Control Center

### Add owner-confidence summary to Control Center overview

**What:** Add a later compact owner-confidence summary to the Control Center
overview so a bot owner can get a fast answer about whether the current setup
still looks okay without turning Control Center into a second Monitoring page.

**Why:** This preserves the good product idea behind the old runtime-health TODO
while keeping the current trust-first implementation focused.

**Context:** This follow-up should stay compact and evidence-based. It may
eventually reuse safe signals such as current mode, readiness state, or a
proven lightweight activity signal, but it should not duplicate Monitoring
logs, reconnect counters, or stream-by-stream diagnostics. Revisit it only
after config trust and invalidation hardening feel stable.

**Effort:** M
**Priority:** P3
**Depends on:** Config trust and invalidation hardening shipping cleanly first

## Stabilization

### Split trade/data backend cleanup into its own delete-first slice

**What:** Run a follow-up backend stabilization pass on
`backend/service/database.py` and `backend/service/data.py` after the
Control Center/config-surface cleanup lands.

**Why:** Phase 1 was deliberately narrowed so cleanup stays coherent. Without a
separate TODO, the backend half of the stabilization goal can disappear after
the first PR ships.

**Context:** The 2026-04-06 office-hours plan and follow-up engineering review
approved a reduced first pass: remove legacy Control Center entry seams, keep
the public `/config/*` API contract stable, and clean up the config
controller/view path first. `database.py` and `data.py` were explicitly
deferred because they belong to a different domain: SQLite recovery, migration
safety, replay/history behavior, and broader data-read semantics. Pick this up
only after the Phase 1 cleanup merges, using the same keep/delete/justify
inventory and delete-before-refactor rule.

**Effort:** M
**Priority:** P2
**Depends on:** Phase 1 Control Center/config stabilization landing cleanly

## Completed

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
