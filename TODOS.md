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

## Autopilot

### Add ranked scarce-bot admission for trusted symbols

**What:** Add a ranked admission seam so symbol trust can decide which
candidate claims limited bot capacity when Moonwalker is full.

**Why:** This is the missing allocation layer after v1 trust scoring and
adaptive take profit. It is the clearest next step from "smarter exits" to
"smarter allocation under pressure."

**Context:** The symbol-memory v1 review explicitly deferred this because
`backend/service/signal_runtime.py` only exposes a boolean max-bots gate today,
and both signal plugins depend on that shape. Revisit after the v1 memory
service, stale fallback, and cockpit read model ship cleanly so the new
admission seam is solving one problem instead of three at once.

**Effort:** L
**Priority:** P2
**Depends on:** Symbol-memory v1 shipping cleanly first

### Promote suggested base order into guarded per-symbol sizing

**What:** Turn the read-only suggested base-order insight into an optional
guarded per-symbol sizing policy once the trust model proves reliable.

**Why:** This is the long-range capital-allocation payoff of symbol memory after
Moonwalker earns operator trust with safer v1 behavior.

**Context:** The approved symbol-memory design intentionally keeps base-order
sizing read-only in v1 because wrong sizing is more dangerous than wrong
wording. Revisit only after operators can see, understand, and trust the
symbol-memory recommendations in the cockpit, and after stale/corrupt snapshot
fallback is proven in production-like testing.

**Effort:** XL
**Priority:** P3
**Depends on:** Symbol-memory v1, cockpit trust visibility, and observed
operator confidence in the recommendations

## Completed

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
