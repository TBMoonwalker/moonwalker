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

### Harden config trust and invalidation in Control Center

**What:** Add explicit config trust states and harden invalidation handling in
the Control Center so owners can tell whether this page is using the latest
saved config and react safely when another tab or client changes it.

**Why:** The immediate product problem is trust, not just transport. Owners need
quiet auto-refresh when a clean tab falls behind, a clear conflict decision when
local drafts are at risk, and faster same-browser invalidation feedback without
turning Control Center into a second Monitoring page.

**Context:** The first pass should ship explicit trust states, quiet
auto-refresh for clean tabs, explicit stale-draft conflict handling, and
browser-local invalidation fanout after save, restore, and live activation,
while keeping the existing focus/interval freshness path for other clients.
Full backend push invalidation across all devices remains a later option only if
real usage shows that this hybrid model is still not trustworthy enough.

**Effort:** M
**Priority:** P2
**Depends on:** Shared hydrated config store and current freshness detection already in the app

## Completed

### Create a repo-level DESIGN.md after the Control Center ships

**Completed:** 2026-03-21

**What shipped:** Added the repo-level `DESIGN.md` and then refined it with the
surface-treatment rule that keeps gradients atmospheric and working panels flat.
