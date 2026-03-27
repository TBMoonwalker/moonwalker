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
