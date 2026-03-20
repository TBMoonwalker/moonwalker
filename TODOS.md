# TODOS

## Control Center

### Extend capability model into runtime operator health

**What:** Extend the reusable capability/status model beyond setup into ongoing operator-health domains such as exchange health, autopilot health, and signal/plugin health.

**Why:** This turns the Control Center from a one-time setup surface into a true operational home over time.

**Context:** The first implementation should focus on setup readiness, safety state, inline fixing, rescue flows, and rollout compatibility. The new capability model should be designed so future concerns can plug in cleanly, but those additional domains do not need to ship in the first pass unless scope expands intentionally.

**Effort:** L
**Priority:** P2
**Depends on:** Initial Control Center capability model shipping cleanly first

### Upgrade config freshness to realtime cross-client invalidation

**What:** Upgrade config freshness from focus/interval stale detection to realtime cross-client invalidation for Control Center state.

**Why:** This removes stale-state windows between multiple connected dashboards if lightweight freshness checks prove insufficient in practice.

**Context:** The first implementation should ship with one shared hydrated config snapshot plus lightweight stale detection and safe refresh behavior. This follow-up only becomes necessary if real multi-client usage shows that polling or focus-based refresh still causes operator confusion.

**Effort:** M
**Priority:** P3
**Depends on:** Shared hydrated config store and lightweight stale detection shipping first

## Design System

### Create a repo-level DESIGN.md after the Control Center ships

**What:** Create a shared `DESIGN.md` that captures Moonwalker's visual vocabulary, interaction tone, spacing and density rules, and accessibility expectations after the Control Center implementation lands.

**Why:** This prevents future frontend work from drifting back into ad-hoc page-by-page design decisions.

**Context:** The Control Center design review intentionally stayed feature-scoped: it fully specified the new operator surface without expanding into a whole-app design-system project. This follow-up should happen after the Control Center ships so the documented patterns are based on real implemented UI, not hypotheticals.

**Effort:** M
**Priority:** P3
**Depends on:** Control Center implementation shipping first

## Completed
