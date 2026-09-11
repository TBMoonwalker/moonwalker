# Audit — `/control-center` (Control Center)

- **Date:** 2026-09-11
- **Target:** `/control-center` and its component tree (`frontend/src/views/ControlCenterView.vue`, `frontend/src/components/control-center/*`, `frontend/src/control-center/*`)
- **Method:** Source + deterministic-detector audit. Live visual capture was **not** possible this run (no headless browser installed; see "Environment / caveats" below), so findings are grounded in the built assets that render plus `impeccable detect` over the source. Per `audit.md`, this is a code-level audit: it reports what is measurable in the implementation, not a subjective design critique.
- **Reference:** `DESIGN.md` (design system + 2026-06-05 live baseline), `PRODUCT.md` (product record), `impeccable` 5-dimension rubric.
- **Detector:** `/Users/tbrandstetter/.config/opencode/skills/impeccable/scripts/impeccable detect` over the Control Center source. Primary findings: **0**. Advisory findings: **1**.

---

## Audit Health Score

| # | Dimension | Score | Key Finding |
|---|-----------|:-----:|-------------|
| 1 | Accessibility | 3 | ARIA live regions, focus flow, and `:focus-visible` are present; gaps limited to a `h1→h3` heading skip in the entry gate and an unguarded 0.5s global theme transition under reduced-motion |
| 2 | Performance | 3 | Route-level code splitting via `router/index.ts`; lazy `Rete.js` canvas with fallback; no `v-html`/`will-change`/layout-thrash. Minor: heavy font `display=swap` + 0.5s global transition |
| 3 | Theming | 2 | Strong `--mw-*` token system with dark variants, but **two dark systems** (CSS `prefers-color-scheme` vs Naive `NConfigProvider`) plus legacy `--color-border` drift and hard-coded brand green in the canvas |
| 4 | Responsive | 3 | Media queries at 767/900/520/640px and a global 44px mobile button guard; inherited 28px pagination + 14px ledger rows from the 2026-06-05 baseline |
| 5 | Implementation Integrity | 3 | Expressive, product-specific system (intent-first gate, mission panel, readiness, ARIA, token system). One detector advisory: `codex-grid-background` in `StrategyCanvasPanel` |
| **Total** | | **14/20** | **Good — address weak dimensions (Theming leads; P0 staging blocks verification)** |

**Rating band:** 14–17 = **Good** (address weak dimensions). The single most valuable action is the P0 staging fix, which unblocks live verification of the P1/P2 items below.

---

## Implementation Integrity Verdict

**PASS** (with one advisory).

The Control Center expresses a coherent, product-specific system: intent-before-breadth entry gate, a single mission panel with one next action, readiness gating, operator-owned evidence rows, a unified `--mw-*` design-token system, and genuine accessibility scaffolding (live regions, focus flow, keyboard-anchored sections). It is not interchangeable with a generic admin panel.

The only detector signal is **advisory** `codex-grid-background` at `StrategyCanvasPanel.vue:120`. This is a **justified near-pass**: that grid sits on a real graph/editing canvas (Rete.js node editor), which the detector's own rule explicitly exempts ("reserve grid overlays for actual canvas, map, blueprint, or measurement surfaces"). No action required unless the canvas can be visually distinguished from a generic grid field.

---

## Executive Summary

- **Audit Health Score: 14/20 (Good).**
- **Issues by severity:** P0 = 1, P1 = 4, P2 = 2, P3 = 3.
- **Top items:**
  1. **[P0]** Live app returns HTTP 500 on `/`/`/control-center`/`/stats` because `backend/static` + `backend/templates` were empty (frontend not staged). Blocks operator UI access *and* live visual verification.
  2. **[P1]** Two independent dark-mode systems (native CSS `prefers-color-scheme` + Naive OS-driven `darkTheme`) can desync; hard-coded Naive `themeOverrides` duplicate tokens.
  3. **[P1]** Token drift: legacy `var(--color-border)` used 5× across 3 files alongside the `--mw-*` system.
  4. **[P1]** Hard-coded brand green `rgba(29,92,73,…)` in `StrategyCanvasPanel.vue` (7×) and entry-card borders, bypassing tokens.
  5. **[P2]** Heading skip `h1→h3` in the entry gate; global 0.5s body color/bg transition not guarded by `prefers-reduced-motion`.
- **Strong positives:** intent-first entry gate + calm next-action patterns are faithfully realized; excellent ARIA/live-region/focus handling; responsive media-query coverage; token system with dark variants.
- **Recommended next commands:** `/impeccable harden` → `/impeccable colorize` → `/impeccable adapt` → `/impeccable clarify` → `/impeccable polish` (priority-ordered below).

---

## Detailed Findings by Severity

### P0 — Blocking

**[P0-1] Frontend not staged → live app 500s on every route**
- **Location:** `backend/static/`, `backend/templates/` (were empty, held only `.emptyfile`); staging logic `run.sh:169-178`.
- **Category:** Implementation Integrity / deploy.
- **Impact:** Every operator route (`/`, `/control-center`, `/stats`, …) returns HTTP 500. The dashboard is the only operational surface; this blocks the operator from reaching the UI and blocks any live visual audit.
- **Cause:** `backend/static/*` and `backend/templates/*` are only populated by `run.sh` (`cp -r frontend/dist/assets backend/static/; cp frontend/dist/index.html backend/templates/`). The running `Litestar` process (PID 39414, port 8130) was started before/without the staging copy, so it serves an empty static root.
- **Recommendation:** Run the staging step (`./run.sh start` rebuilds + stages, `run.sh:169-178`) and restart the backend; confirm `curl -s -o /dev/null -w "%{http_code}" http://localhost:8130/control-center` returns 200. Add a guard/warning in `run.sh` (and optionally a startup smoke-check in `backend/app.py` lifespan) when `backend/templates/index.html` is absent so the 500 is loud and explainable instead of silent.
- **Suggested command:** `/impeccable harden` (start-up/edge-case resilience) — or a one-line deploy fix.

---

### P1 — Major

**[P1-1] Dark mode is split across two uncoordinated systems**
- **Location:** `frontend/src/assets/base.css:54-86` (`@media (prefers-color-scheme: dark)`) vs `frontend/src/App.vue:25-74` (`useOsTheme()` + `darkTheme` + `themeOverrides`).
- **Category:** Theming.
- **Impact:** The `:root` design-token layer (surfaces, text, borders) is driven by the *OS* color-scheme (base.css), while Naive UI components are driven by a *separate* `NConfigProvider` dark theme (App.vue). Both read the OS scheme independently, so any future user toggle, forced theme, or media-query override desyncs CSS surfaces from Naive components — panels and content render in mismatched colors.
- **Recommendation:** Single source of truth for the theme. Either (a) drive both the CSS variables and the Naive theme from one reactive `useColorScheme`/store with an explicit `auto` default, or (b) if OS-only is intentional, document it and reconcile the hard-coded `themeOverrides` hex values (see P1-2) with base.css so they can't drift.
- **Suggested command:** `/impeccable colorize`.

**[P1-2] Design-token drift: legacy `var(--color-border)` + hard-coded Naive `themeOverrides`**
- **Location:** `var(--color-border)` → `ControlCenterOwnerConfidenceSummary.vue:442`, `ControlCenterOverviewWorkspace.vue:200,238,262`. Naive `themeOverrides` hard-coded hex → `App.vue:27-74`.
- **Category:** Theming.
- **Impact:** The project committed to a `--mw-*` token system; `base.css:48` defines `--color-border: rgba(24,33,29,0.08)` as a *legacy alias*, yet 3 Control Center files still consume it. Mixing token families makes dark-mode theming error-prone. The Naive `themeOverrides` block re-hard-codes `#245f4e`, `#356d86`, `#111714`, `#1d2823`, `rgba(213,219,213,0.2)` … which duplicate base.css values and will silently fall out of sync when base.css is retuned.
- **Recommendation:** Replace the 5 `var(--color-border)` uses with `var(--mw-color-border-strong)` (or the correct `--mw-*` token per intent). Generate Naive `themeOverrides` from the token values (import the CSS custom properties or a shared TS token map) so the single source of truth lives in one place.
- **Suggested command:** `/impeccable colorize`.

**[P1-3] Hard-coded brand color in the strategy canvas (bypasses tokens)**
- **Location:** `frontend/src/components/control-center/StrategyCanvasPanel.vue` — `rgba(29,92,73,…)` at ~152,156,237,251,257 + `rgba(36,95,78,…)` at 251,309,314 + brass `rgba(183,138,46,0.82)` at 202. Also `.entry-choice-card` borders use `rgba(29,92,73,0.14/0.16)` in `ControlCenterSetupEntryGate.vue:110,124`.
- **Category:** Theming / Implementation Integrity.
- **Impact:** `rgba(29,92,73,*)` is `--mw-color-primary` (`#1d5c49`) hard-coded. These do **not** retheme in dark mode (the CSS dark block overrides `--mw-color-primary: #245f4e` but not these literals), so canvas node edges/accents keep the light-theme green and lose contrast on dark surfaces.
- **Recommendation:** Introduce token variants with a configurable alpha, e.g. `--mw-color-primary-alpha: color-mix(in srgb, var(--mw-color-primary) var(--_a), transparent)` or per-use CSS vars, and reference them. This keeps the canvas themable and honors the DESIGN.md "flat surfaces / restraint" rule.
- **Suggested command:** `/impeccable colorize`.

**[P1-4] Reduced-motion not honored for the global theme transition**
- **Location:** `frontend/src/assets/base.css:100-102` — `transition: color 0.5s, background-color 0.5s;` with no `@media (prefers-reduced-motion)` guard.
- **Category:** Accessibility.
- **Impact:** On theme/scheme change the whole page animates for 500ms. `prefers-reduced-motion` users (and anyone switching theme) get a long cross-fade of every surface. This is the only unguarded motion in the app — `StrategyCanvasPanel.vue:265` correctly gates its transition under `@media (prefers-reduced-motion: no-preference)`, so the pattern already exists in the codebase and just isn't applied globally.
- **WCAG:** 2.3.3 / 2.3.1 spirit (animation that can be controlled).
- **Recommendation:** Wrap the global transition in `@media (prefers-reduced-motion: no-preference)` or add a `@media (prefers-reduced-motion: reduce){ *{transition-duration:0.01ms!important} }` guard.
- **Suggested command:** `/impeccable animate` (or `/impeccable harden`).

---

### P2 — Minor

**[P2-1] Heading-level skip in the entry gate (`h1 → h3`)**
- **Location:** `frontend/src/components/control-center/ControlCenterSetupEntryGate.vue:19` (`<h1>How do you want to begin?</h1>`) then `:31`/`:52` (`<h3 class="entry-choice-title">`).
- **Category:** Accessibility / semantic HTML.
- **Impact:** Screen-reader heading navigation jumps from h1 to h3, implying a missing h2 and fragmenting the outline of the most important first-run screen.
- **Recommendation:** Make the two card titles `h2` (siblings under the h1), or restructure so the hierarchy is h1 → h2 for the choice cards.
- **Suggested command:** `/impeccable clarify` / `/impeccable polish`.

**[P2-2] Ledger / table body copy at 14px vs DESIGN.md 16px default**
- **Location:** `frontend/src/assets/main.css:213` (`.ledger-panel .n-data-table { --n-font-size: 14px; }`) and `:233` (`font-size: 12px` headers).
- **Category:** Theming / Responsive (carried from 2026-06-05 baseline `DESIGN.md:303`).
- **Impact:** The 2026-06-05 baseline flagged "body 14px (Naive UI default) → should be 16px." Tables are a defensible exception (DENSE tables), but verify this is intentional and scoped to data tables only, not leaking to body copy elsewhere.
- **Recommendation:** Confirm 14px is intentional for dense tables (documented as the "compact for advanced" density in DESIGN.md:53); if body text elsewhere is 14px, raise to 16px.
- **Suggested command:** `/impeccable typeset`.

---

### P3 — Polish

**[P3-1] Pagination / small controls under 44px (from 2026-06-05 baseline)**
- **Location:** `DESIGN.md:304` (28×28px pagination on mobile; 375px truncation). Not reproduced in Control Center component code — likely Naive `n-pagination`/`n-data-table` defaults.
- **Category:** Responsive / Accessibility.
- **Impact:** Sub-44px tap targets on mobile; WCAG 2.5.5 pointer/44px target guidance.
- **Recommendation:** The Control Center already adds a global `@media (max-width:767px){ .control-center-page :deep(.n-button){ min-height:44px !important } }` guard at `ControlCenterView.vue:645`; extend the same guard to `.n-pagination-item` / `.n-data-table` pagination, and fix the 375px truncation.
- **Suggested command:** `/impeccable adapt`.

**[P3-2] `main` landmark nesting**
- **Location:** `frontend/src/App.vue:354` (`<main class="app-content">`) contains `<router-view>` → each view is a `<div class="page-shell">`; only `StrategyCanvasPanel.vue:36` uses a nested `<main class="strategy-canvas-shell">`.
- **Category:** Accessibility / semantic HTML.
- **Impact:** A nested `<main>` inside the app-level `main` can confuse landmark navigation. (Single `<main>` at app level is correct; the nested one is the issue.)
- **Recommendation:** Change `StrategyCanvasPanel`'s `<main class="strategy-canvas-shell">` to `<section aria-label="Strategy graph">` (it already has `aria-label`), keeping one app-level landmark.
- **Suggested command:** `/impeccable polish`.

**[P3-3] Detector advisory: `codex-grid-background` in `StrategyCanvasPanel`**
- **Location:** `frontend/src/components/control-center/StrategyCanvasPanel.vue:120` (two-axis grid-line gradient background).
- **Category:** Implementation Integrity.
- **Impact:** Detector flags a generated-UI grid signature. **Justified near-pass** — this is a genuine node-editing canvas, which the rule explicitly allows. No defect; logged for completeness.
- **Recommendation:** None required. Optionally add an `// impeccable-disable codex-grid-background` annotation so the detector stops re-flagging a known-OK case.
- **Suggested command:** `/impeccable polish` (optional annotation only).

---

## Patterns & Systemic Issues

1. **Token-vs-literal drift (systemic).** The `--mw-*` system is real and mostly used, but three bypass patterns repeat: legacy `var(--color-border)` (5×), hard-coded brand `rgba(29,92,73,*)` in the canvas (7×), and hard-coded duplicates in Naive `themeOverrides` (`App.vue`). One fix each resolves it; together they are the main reason Theming scores 2. → unify on tokens.
2. **Dark-mode coordination (systemic).** Two theme drivers (CSS OS `prefers-color-scheme`, Naive `NConfigProvider`) with duplicated palettes. → single source of truth (P1-1/P1-2).
3. **`prefers-reduced-motion` is applied ad hoc.** Correct in `StrategyCanvasPanel` but missing for the global transition. → add one global guard (P1-4).

## Positive Findings (keep and replicate)

- **Intent-first entry gate is real, not a slogan.** `ControlCenterSetupEntryGate.vue` implements exactly the DESIGN.md "How do you want to begin? → Restore / New setup" flow with consequence-aware copy. Strong.
- **Calm, next-action patterns.** `ControlCenterMissionPanel` (one next action, `role="status" aria-live="polite"`) and `ControlCenterView.vue:415` (`<div class="sr-only" aria-live="polite" aria-atomic="true">`) plus `control-center/focusFlow.ts` and the `:focus-visible` styled anchors (`ControlCenterSetupTaskSection.vue:38`, …) show real a11y investment — rare and good.
- **Responsive coverage.** Media queries at 767/900/520/640px and the global 44px mobile button guard (`ControlCenterView.vue:645`) show intentional mobile work.
- **Performance hygiene.** Route-level code splitting (`router/index.ts`), lazy `Rete.js` load with status/fallback (`StrategyCanvasPanel.vue:71-82`), no `v-html`, no broad `will-change`, proper `:key` on all `v-for`. Solid for the "fast, lean" band.
- **Token system with dark variants** exists and is correct in `base.css` (including a `prefers-color-scheme: dark` block); the work is *adoption consistency*, not creation.

---

## Environment / Caveats

- **No live visual capture.** No headless browser (Playwright/Puppeteer/Chromium) is installed on this machine, and the live app 500'd on staging at the start of the run (P0-1). Findings are therefore **source + deterministic-detector based**, which is exactly what `impeccable audit` is designed for. Contrast ratios, rendered font sizes, and touch-target pixel sizes could **not** be measured live this run — after P0 is fixed, re-run `/impeccable audit` (or `/impeccable live` + a browser) to verify P1-1/P1-3 dark-mode contrast and P2-2/P3-1 sizing on screen.
- **False positives excluded after verification:** `#dca` (`ControlCenterAdvancedMode.vue:79`, `ControlCenterSetupMode.vue:172`) is a **Vue named slot** (`<template #dca>`), not a color; `#18413a` is the real token `--mw-color-primary-strong`. Neither is an issue.
- **Detector result:** 0 primary findings, 1 advisory (`codex-grid-background`, justified — see P3-3).

---

## Recommended Actions (priority order)

1. **[P0] `/impeccable harden`** — fix the staging 500 (rebuild + `run.sh` staging + a startup smoke-check). Unblocks live verification of everything below.
2. **[P1] `/impeccable colorize`** — unify the single source of truth for the theme: reconcile the two dark-mode systems (P1-1), replace legacy `--color-border` (P1-2), and tokenize the canvas brand colors (P1-3).
3. **[P1] `/impeccable animate`** — guard the global 0.5s transition with `prefers-reduced-motion` (P1-4).
4. **[P2] `/impeccable clarify`** — fix the `h1→h3` skip in the entry gate (P2-1).
5. **[P2/P3] `/impeccable adapt`** — extend the 44px touch-target guard to pagination and fix 375px truncation (P3-1); confirm 14px table density is intentional (P2-2).
6. **[polish] `/impeccable polish`** — de-nest the canvas `<main>` (P3-2); add the detector ignore annotation (P3-3). Final consolidation pass.

> You can ask me to run these one at a time, all at once, or in any order you prefer.
>
> Re-run `/impeccable audit` after fixes to see your score improve.

---

## Remediation Applied (session 2026-09-11, build mode)

Applied in a follow-up session after the audit. All changes verified:
**1000 backend tests pass**, **379 frontend legacy regression tests pass**,
`vue-tsc` clean, `vite build` succeeds, and `black`/`ruff`/`isort`/`mypy`
clean on the touched backend files.

| Finding | Status | Change |
|---|---|---|
| **P0-1** staging 500 | **Fixed** | `controller/frontend.py` `frontend_staging_warning()` returns `None`/actionable message; `_serve_vue_path` raises a clear 500 when `index.html` is missing. `app.py` `startup()` logs it non-fatally (engine keeps running). `run.sh` aborts if assets don't stage. The live staging gap itself is already resolved on the running instance. |
| **P1-2** legacy `--color-border` | **Fixed** | 4 usages across `ControlCenterOverviewWorkspace.vue` / `ControlCenterOwnerConfidenceSummary.vue` → `--mw-color-border-strong`. |
| **P1-3** hard-coded brand color | **Fixed** | `StrategyCanvasPanel.vue` brand green/ink/brass literals → `color-mix(in srgb, var(--mw-color-*) N%, transparent)`. Now themeable in dark mode. |
| **P1-4** reduced-motion | **Fixed** | `base.css` global 0.5s `color`/`background` transition gated under `@media (prefers-reduced-motion: no-preference)`, matching the existing `StrategyCanvasPanel` pattern. |
| **P2-1** heading skip | **Fixed** | `ControlCenterSetupEntryGate.vue` card titles `h3 → h2`. |
| **P3-1** 44px pagination | **Fixed** | `ControlCenterView.vue` 44px guard extended to `.n-pagination-item` + `.n-base-btn`. |
| **P3-2** nested `<main>` | **Fixed** | `StrategyCanvasPanel.vue` outer `<main>` → `<section aria-label>` (one app-level `main`). |
| **P1-1** dual dark-mode systems | **Deferred** | Both systems (CSS `prefers-color-scheme` + Naive `useOsTheme()`) currently track the *same* OS signal and the hard-coded `themeOverrides` hexes match `base.css` dark values — so the system is **in sync today**. Risk is latent (only desyncs if a manual theme toggle is added later). Unifying the literal source is a cross-cutting theme refactor; flagged for a dedicated, visually-tested session. |
| **P3-3** `codex-grid-background` | **Skipped** | Justified — the grid sits on a genuine `Rete.js` node canvas, which the detector's own rule exempts. No reliable ignore-directive token exists in the detector binary; a guessed annotation would be a dead comment. |

### Pre-existing issues discovered (NOT caused by this work)

- **Frontend test env mismatch (resolved):** vitest reported 96/96 failures under the active shell's **Node v26.8.1** — `window.localStorage` was undefined, so `tests-vitest/setup.ts:7` (`window.localStorage.clear()`) threw for every jsdom test, on a *clean* tree (confirmed by stashing all changes). Root cause: Node v26 is a pre-release far ahead of jsdom 29 / vitest 4's supported range. **Resolution:** run the project's pinned Node — `.nvmrc` = `24.18.0` (Homebrew `node@24` at `/opt/homebrew/Cellar/node@24/24.20.0/bin/node`). Under Node 24 all **96 vitest tests pass**. No code change; the environment simply needs the pinned Node on `PATH`.
- **Tooling drift:** the local `.venv` (and the release `slot-a` venv) lacked `pytest`/`pytest-asyncio`/`pytest-cov` and the formatters/linter; dev tools were installed locally to run the gates. Worth confirming `install_python_dependencies.sh` provisions dev deps for CI.
- **Pre-existing `isort` drift (fixed):** `backend/service/backtest.py` had unsorted (`service.config_views` + `service.dca_decision` out of order) — fails `isort --check-only` even at HEAD, in a file this work never touched. Resolved by a pure mechanical reorder (no behavior change). Full CI now green: `cd scripts && ./ci.sh` → **All checks passed** under Node 24.

**Next:** with a headless browser available, run `/impeccable live` against `:8130/control-center` to measure rendered dark-mode contrast and mobile touch-target pixel sizes (the items this source audit could not verify visually).
