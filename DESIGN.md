---
name: Moonwalker
description: Charcoal operator console with selective green accents for a self-hosted trading bot.
colors:
  primary: "#276b47"
  primary-strong: "#205a3b"
  primary-soft: "#e5f3e8"
  secondary: "#995d14"
  surface-base: "#f5f5f7"
  surface-raised: "#ededf0"
  surface-panel: "#ffffff"
  border: "#d9d9e0"
  text-primary: "#19191d"
  text-secondary: "#45454e"
  text-muted: "#65656f"
  success: "#157651"
  warning: "#995d14"
  warning-soft: "#fff2dd"
  error: "#b4443f"
  info: "#356d86"
typography:
  display:
    fontFamily: "General Sans, Source Sans 3, sans-serif"
    fontSize: "clamp(1.5rem, 2vw, 2.25rem)"
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: "-0.03em"
  body:
    fontFamily: "General Sans, Source Sans 3, sans-serif"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: "normal"
  label:
    fontFamily: "General Sans, Source Sans 3, sans-serif"
    fontSize: "14px"
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: "normal"
  mono:
    fontFamily: "IBM Plex Mono, monospace"
    fontSize: "14px"
    fontWeight: 450
    lineHeight: 1.4
    letterSpacing: "normal"
rounded:
  sm: "6px"
  md: "10px"
  lg: "14px"
  full: "9999px"
spacing:
  "2xs": "4px"
  "xs": "8px"
  "sm": "12px"
  "md": "16px"
  "lg": "24px"
  "xl": "32px"
  "2xl": "48px"
  "3xl": "64px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.surface-panel}"
    typography: "label"
    rounded: "{rounded.md}"
    padding: "9px 18px"
  button-secondary:
    backgroundColor: "{colors.surface-panel}"
    textColor: "{colors.primary}"
    typography: "label"
    rounded: "{rounded.md}"
    padding: "9px 18px"
  dashboard-card:
    backgroundColor: "{colors.surface-panel}"
    textColor: "{colors.text-primary}"
    typography: "body"
    rounded: "{rounded.md}"
    padding: "16px"
  status-tag:
    backgroundColor: "{colors.primary-soft}"
    textColor: "{colors.primary-strong}"
    typography: "label"
    rounded: "{rounded.full}"
    padding: "4px 10px"
  input-field:
    backgroundColor: "{colors.surface-panel}"
    textColor: "{colors.text-primary}"
    typography: "body"
    rounded: "{rounded.md}"
    padding: "9px 12px"
---

# Design System: Moonwalker

## Overview

Moonwalker is a calm trading workstation. Its visual language now uses a charcoal and neutral-grey shell with green reserved for selected navigation, key figures, chart emphasis, focus, and primary actions. It takes inspiration from the density and typographic clarity of the approved mockup while retaining Moonwalker's astronaut logo, product name, operational copy, and Naive UI components. Neither the wordmark nor the “Trading overview” title carries an ornamental underscore.

The dashboard presents live status and actions in a left navigation rail, a slim status bar, a Moonwalker status card with a separate Autopilot section, side-by-side performance and portfolio exposure cards, and the existing trade tables. Net profit and loss is the portfolio card's main figure; portfolio value and funds in deals appear beneath the budget bar. Figures are derived from current WebSocket and configuration data; missing feeds are shown as unavailable rather than invented. The Control Center keeps its intent-first setup flow and safety gates.

Statistics, Backtest, Monitoring, Autopilot Memory, Configuration, Strategy Builder, and Utilities use the same compact page heading and neutral panel treatment. Configuration's mission panel appears below that heading only for readiness, draft, recovery, and freshness states. Within those views, semantic status tags and warnings retain their meaning; ordinary cards and labels stay neutral. Naive UI remains the control and data-display framework throughout.

## Colors

Light mode uses base `#f5f5f7`, rail `#ededf0`, panels `#ffffff`, border `#d9d9e0`, primary text `#19191d`, and accent `#276b47`. Dark mode uses base `#19191d`, rail `#17171b`, panels `#222227`, raised panels `#28282e`, border `#34343b`, primary text `#f5f5f7`, and accent `#9cdb73`. The semantic success, warning, error, and info colors remain separate from the brand accent.

Use green selectively on active navigation, primary controls, highlighted data, and chart emphasis. Keep most headings, labels, cards, and backgrounds neutral. Warning and failure states retain amber and red; a positive financial value alone does not imply a healthy trading state. CSS custom properties in `frontend/src/assets/base.css` mirror `frontend/src/theme/tokens.ts`; the theme drift test enforces their correspondence.

## Typography

General Sans is the display and UI face, with Source Sans 3 as fallback. IBM Plex Mono is for monetary values, ratios, diagnostics, and other tabular figures. The scale remains `12 / 14 / 16 / 20 / 24 / 32 / 40 / 56 px`; body text defaults to 16px, labels to 14px, and dense table text may be 14px. Use short, plain labels and tabular numerals. Preserve readable system fallbacks when web fonts are unavailable.

## Layout

Desktop uses a 224px left rail and a 64px top bar. The content width is at most 1500px. The trading overview starts with a compact Moonwalker status card containing admission and Autopilot sections. The wide Performance card sits beside a narrower, taller portfolio exposure card; its chart fills the available card height. Net profit and loss is the sole prominent financial figure. The budget bar is one continuous line scaled to the effective capital budget, with segments for funds in deals, open and pending order reserves, available to trade, and budget awaiting exchange funds. Its legend shows those amounts; exchange free and portfolio value sit below the bar. When budget telemetry is unavailable, the card says so rather than presenting exchange balance as a budget. At narrower widths the two cards stack and the trade selector wraps. Configuration keeps its one-task-at-a-time first-run flow and opens on Setup after readiness.

Spacing follows `4 / 8 / 12 / 16 / 24 / 32 / 48 / 64 px`. Use borders, surface differences, and whitespace for hierarchy. Preserve the actual Moonwalker logo. Do not add decorative punctuation to the product name or page headings.

## Elevation & Depth

Working panels are flat at rest with a 1px neutral border. A soft shadow may be used for exceptional emphasis or transient hover state; it is not the default for cards. Do not use gradients on working surfaces. Dark mode gains depth through adjacent charcoal values rather than green fills.

## Shapes

Use the existing radius family: 6px for compact controls, 10px for cards and fields, 14px for large shells, and full radius for true pills. One-pixel borders define panels and separators.

## Components

Keep Naive UI as the component framework. Apply the design through `NConfigProvider` overrides and the Moonwalker CSS tokens. Reuse Naive UI menus, tabs, cards, tables, tags, dialogs, and controls instead of creating a parallel component library. Selected navigation uses a neutral surface and a green icon/accent; buttons and focus use the green brand tone. Readiness and trade admission retain their semantic status colors and accessible labels.

The real dashboard keeps all open, closed, and unsellable trade tables and their actions. Open trades get the full content width so columns and row actions remain visible on large windows. Trade-table primary text shares one UI face and size, with tabular numerals; secondary details are one step smaller. Larger monetary summaries may use the mono face. The performance switcher starts on ALL with the cumulative profit and funds-in-deals line chart, and offers historical profit bar charts for 1D (daily), 30D (monthly), and 1Y (yearly). The historical charts keep their running-average line. Their descriptions identify the actual aggregation periods; the “ALL” feed currently contains at most the latest 12 months. Explanatory labels must accurately identify those data; exchange balance is not a complete exchange portfolio. On mobile, the navigation rail becomes a menu button that opens a drawer with the same destinations.

## Do's and Don'ts

### Do
- Ask the operator for intent before exposing setup breadth.
- Give every editable setting one canonical home.
- Keep working surfaces neutral and use green as a selective accent.
- Use live data, explicit loading states, and honest metric labels.
- Keep visible keyboard focus and minimum 44px touch targets on mobile.
- Preserve trade admission, delisting, and pause warnings near the trades they affect.

### Don't
- Copy another product's wordmark decoration or substitute its logo.
- Turn every surface or heading green.
- Invent portfolio, exposure, or alert values when feeds are unavailable.
- Duplicate normal editable settings between Setup and Advanced.
- Apply gradients to headers, cards, shells, or setup panels.

---

The sections below preserve Moonwalker's operator flow, Control Center information architecture, accessibility, and implementation rules.

## Operator UX Rules

### Core Principle
Moonwalker must ask the operator for intent before exposing breadth.

The first-run experience should not begin with a mode strip or a wall of fields.
It should begin with one clear question:

`How do you want to begin?`

- `Restore existing Moonwalker installation`
- `Start a new setup`

This is the correct first decision because it is intent-based, not identity-based.
Operators know whether they are migrating an existing instance. They do not
reliably know whether they should self-identify as "advanced."

### First-Run Flow

```text
FIRST RUN
|
|-- Entry Choice
|    |-- Restore existing installation
|    `-- Start new setup
|
|-- If Restore
|    |-- Choose config-only or full backup
|    |-- Perform restore
|    `-- Land in readiness review
|
`-- If Start New
     |-- Choose setup style
     |    |-- Guided setup (recommended)
     |    `-- Full control
     |
     `-- Complete safe dry-run setup
```

### Restore Is Not "Advanced"
- Restore is an entry workflow and a utility.
- On first run, restore belongs on the opening decision screen.
- After the instance is running, restore belongs in `Utilities`.
- This is acceptable duplication because it is the same action at two different lifecycle moments, not the same setting living in two different homes.

### Setup Style Choice
If the operator chooses `Start a new setup`, the second decision is:

`How do you want to set up Moonwalker today?`

- `Guided setup (recommended)`
- `Full control`

Rules:
- This choice changes presentation, not configuration ownership.
- It is reversible at any time during setup.
- It is remembered per browser session or local preference.
- It does not create a second parallel settings model.

### Visibility Rules

#### Before Readiness
- Show only the setup surface as the primary destination.
- Do not show `Advanced` or operational utilities as equal first-run peers.
- If needed, keep secondary escapes subtle:
   - `Restore instead`
   - `See all controls`
   - `Skip to advanced setup`
- The page should feel like a guided operator flow, not a dashboard plus tabs.

#### Guided Setup
- Show one active task group at a time.
- Completed groups collapse into short reassuring summaries.
- Future groups remain visible but quieter.
- Expert-only controls remain hidden.

#### Full Control Setup
- Use the same setup task groups and the same route.
- Reveal expert controls inline within those groups.
- Never fork into a separate advanced page during first run.

#### After Safe Dry-Run Readiness
- Keep `Setup` as the default Configuration home.
- Unlock `Advanced` as the full-density tuning surface.
- Show a guarded live-trading readiness review at the end of Setup for a saved, ready dry-run configuration.
- Keep `Strategy Builder` and `Utilities` as separate navigation destinations.

## Control Center Information Architecture

### First Run

```text
CONTROL CENTER
|
|-- Entry / Setup Gateway
|    |-- Restore existing installation
|    `-- Start new setup
|
`-- Setup Workspace
     |-- Guided or Full Control
     |-- One dominant active task
     |-- Collapsed completed tasks
     `-- Save / review readiness
```

### Returning Healthy Operator

```text
CONFIGURATION
|
|-- Compact configuration header
|    |-- draft/save state
|    `-- stale snapshot or readiness blocker when actionable
|
|-- Setup (default)
|    `-- Live trading readiness review when safe dry run is ready
`-- Advanced

SEPARATE DESTINATIONS
|-- Trading Overview: operating status and Autopilot summary
|-- Strategy Builder
|-- Utilities
|-- Autopilot Memory
`-- Monitoring
```

### One-Home Rule
Every configuration field gets exactly one canonical visible home.

- Essentials live in `Setup`
- Expert tuning lives in `Advanced`
- Runtime status lives in Trading Overview, Autopilot Memory, or Monitoring.
- Pause/Resume Moonwalker lives in the persistent top bar.
- Autopilot on/off lives with Autopilot settings in Advanced.
- Live activation lives in the guarded readiness review at the end of Setup.
- Backup/restore and connectivity tests live in Utilities.

No field should appear as a normal editable control in both Setup and Advanced.
If Advanced extends an area already introduced in Setup, it should do so by
adding deeper controls, not by restating the same fields.

## Screen-Level Guidance

### 1. Entry Screen
- Headline: `How do you want to begin?`
- Two large action cards:
   - `Restore existing installation`
   - `Start a new setup`
- Supporting copy should explain consequences, not implementation details.
- This screen should be visually quieter than Trading Overview and decisive about the next setup action.

### 2. Guided Setup
- One dominant mission panel: current progress + next action
- One expanded task section
- Quiet progress row or checklist summaries
- No expert toggles, no dense utilities, no same-weight mode strip

### 3. Full Control Setup
- Same page structure as Guided Setup
- Higher field density
- Expert reveals inline in the relevant section
- Still anchored on "finish safe dry run," not on "browse every option"

### 4. Readiness Review After Restore
- Do not drop the user into raw forms immediately after restore.
- Show a review state:
   - what was imported
   - whether the instance is safe for dry run
   - what still needs attention
   - one next action

### 5. Configuration After Readiness
- Setup remains the landing surface.
- Show the setup groups as collapsed links; expand the requested group when selected.
- Keep the header compact; show save state, stale configuration, and blockers only when actionable.
- Put the guarded live activation action after the Setup tasks.
- Do not repeat runtime, Autopilot, or Monitoring summaries here.

### 6. Advanced
- Dense, deliberate, operator-owned tuning
- Group by expert domain, not by leftover form inheritance
- Never used as the first-run dumping ground

### 7. Utilities
- Backup / restore
- Connectivity tests
- Maintenance actions
- Outcomes should be explicit and separate from draft editing

## Copy Rules
- Prefer intent-based labels over self-labeling:
   - good: `Restore existing installation`
   - good: `Start a new setup`
   - good: `Guided setup`
   - good: `Full control`
   - bad: `Beginner`
   - bad: `Advanced user`
- Use state-first headlines
- Keep helper text short, operational, and consequence-aware
- Use `Configuration` for the setup and tuning destination.

## Accessibility Requirements
- The first-run entry choice must be fully keyboard navigable and understandable without color.
- Guided task expansion must preserve clear focus order.
- Revealing expert controls inline must move focus predictably and announce the change.
- Restore outcomes and readiness review states must use ARIA live regions.
- Primary actions must meet minimum touch target sizes (44px).

## Implementation Guardrails
- Keep first-run guidance while making returning Configuration task-focused.
- Do not show all modes at equal weight during first run.
- Do not expose expert toggles inside Guided Setup.
- Do not make restore discoverable only inside Advanced or Utilities during onboarding.
- Do not duplicate normal editable settings between Setup and Advanced.
- Prefer explicit task ownership over component reuse when reuse harms clarity.

## Motion
- **Approach:** Minimal-functional
- **Easing:** enter `cubic-bezier(0.2, 0.8, 0.2, 1)`, exit `cubic-bezier(0.4, 0, 1, 1)`, move `cubic-bezier(0.2, 0.7, 0.2, 1)`
- **Duration:** micro `80ms`, short `160ms`, medium `260ms`, long `420ms`

## Historical Verified Baseline (Live-Measured, 2026-06-05)

These values describe the previous design, measured on 2026-06-05 at http://192.168.6.5:8160/stats. They are retained as historical evidence and do not describe the current palette or typography.

### Fonts Rendered
| Font | Where | Matches Design System? |
|------|-------|----------------------|
| Space Grotesk | Display/Hero | Yes |
| Source Sans 3 | Body, UI labels | Yes |
| IBM Plex Mono | Data/Tables (declared) | Yes |

### Colors Rendered
| Value | Role | Matches? |
|-------|------|----------|
| #1D5C49 | Primary (operator green) | Yes |
| #2E7D5B | Success | Yes |
| #B4443F | Error | Yes |
| #18211D | Primary text | Yes |
| #33403A | Strong secondary text | Yes |
| #8A948D | Muted text | Yes |
| #F7F8F6 | Surface base | Yes |

### Historical Audit Notes

The following notes predate the 2026-09-28 dashboard redesign. Recheck them against a data-fed build before treating any status as current.

_Re-checked 2026-09-24 against the tokenized, a11y-1.0 build by source-truth grep — no live pass. An absent override or fix means the deviation is still open; an explicit source value means it is resolved there._

| Issue | Current | Should Be | Severity |
|-------|---------|-----------|----------|
| Body font size | **Resolved at document scope.** Base document body is `16px` (`base.css` `body`, line 149); the mission/alert copy band is `16px` (T4, 2026-09-23). `14px` remains on component labels (buttons/tags/nav) and dense ledger table cells (`.n-data-table --n-font-size: 14px`) — documented intent in this system, not a deviation. | `16px` per scale (document scope) | Resolved (base) · informational (component labels by design) |
| Pagination touch targets | **Resolved (2026-09-24).** `44px` now covers every paged surface: stats-table pagination (`.ledger-panel`/`.ai-trust-card`, `StatisticsView.vue:1200`, ≤767px), control-center pages (`ControlCenterView.vue:643`, ≤767px), mobile **row-action** buttons (`TradesView.vue:683`, ≤520px), and — added this arc — the three paged trade feeds (Open/Closed/Unsellable), whose Naive `NDataTable` pagination renders inside `.ledger-panel` in `TradesView.vue` (new `:deep(.n-pagination-item)` rule at the foot of its `@media(max-width:520px)` block, mirroring `StatisticsView.vue`). Live CSSOM-verified that day: the rule is loaded, gated to `≤520px`, inert at `>520px` (an injected test item measured 0px wide at 800px), and its selector specificity (`0,0,3`) beats Naive's base `.n-pagination-item` (`0,0,1`), so at 375px the feed items resolve to 44×44px. (A 375px eyeball is skipped — this browser toolset has no viewport emulation — but the result is deterministic from the gated high-specificity rule; CI-built into `TradesView-*.css`.) | `44x44px` minimum on mobile | **Resolved** (all paged surfaces: stats, control-center, row-actions, 3 trade feeds) |
| Mobile text truncation | **Open (unverified 375px).** Re-audited 2026-09-24: `text-overflow:ellipsis` **does** exist in source — on the ledger symbol cell `.trade-symbol-main` (`TradesView.vue`, at both the `≤767px` gate, line 604, and the `≤520px` gate, line 661) — so the earlier "no ellipsis anywhere" note was a false negative (a `*.css`-only grep never looked at the `.vue` scoped `<style>` blocks). Responsive guards exist (`@media(max-width:767px)` + `520px` in `main.css`, `white-space:normal` tab-wrap at ≤520px). A live clip-scan (`scrollWidth>clientWidth`) on a data-less shell at 800px returned **0 candidates** (desktop has room); the 2026-06-05 `"les mo"` @375px case cannot be reproduced without viewport emulation (absent in this browser toolset) plus live trade data, so it stays open pending a device-emulated, data-fed re-check. | Full text with ellipsis on narrow cells | **Low** (open; re-check on a device-emulated, data-fed session) |

### Historical Performance Baseline
| Metric | Value |
|--------|-------|
| TTFB | 10ms |
| DOM Ready | 70ms |
| Full Load | 72ms |

### Historical Accessibility Score
- **Re-measured 2026-09-24: Lighthouse Accessibility `1.0`** (was `0.96` on 2026-09-23); **Best Practices `1.0`**. Vehicle: fresh production build on a throwaway loopback `:4173` — a data-independent shell, so the score reflects theme + a11y, not live market data.
- Drivers of the `0.96`→`1.0` recovery: (a) the admission-pill status text set to `--mw-color-text-primary` — scheme-flipping `#18211d` (light) / `#f7f8f6` (dark), measured `14.06:1` light / `12.13:1` dark, both clear 4.5:1 AA against the green wash that inverts polarity per scheme; (b) `text-muted` `#8a948d`→`#646e66` (2026-09-23).
- Remaining Lighthouse flags are `meta-description` / `robots.txt` — SEO metadata, **not** accessibility — so no a11y work remains.

## Decisions Log
| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-09-28 | Adopted the approved charcoal dashboard layout and restrained green brand accent, retained the Moonwalker logo and Naive UI, and removed decorative underscores | Distinguishes Moonwalker from the reference design while preserving its operator workflow |
| 2026-03-21 | Added repo-level DESIGN.md | Moonwalker had Control Center design intent but no repo-level design source of truth |
| 2026-03-21 | Made first-run begin with `Restore existing installation` vs `Start a new setup` | Intent is clearer and safer than asking the user whether they are "advanced" |
| 2026-03-21 | Made `Guided setup` vs `Full control` the second decision | This preserves expert agency without forking the information architecture |
| 2026-03-21 | Declared restore a first-run entry workflow and a later utility, not an advanced setting | Restore is lifecycle-dependent, not expertise-dependent |
| 2026-03-21 | Declared one-home rule for editable settings | Duplicate fields between Setup and Advanced destroy operator focus |
| 2026-03-21 | Reserved gradients for atmosphere and rare emphasis, not core work surfaces | Flat panels preserve calm hierarchy and keep dark mode from feeling noisy |
| 2026-06-05 | Added verified baseline section | Live-measured values confirm design system compliance; deviations tracked for remediation |
| 2026-09-12 | Canonicalized DESIGN.md to the 8-section format with YAML frontmatter tokens | Tokens extracted from `frontend/src/assets/base.css` `--mw-*` custom properties; incumbent operator-UX content preserved as extra sections |
| 2026-09-23 | Control-center design review (live Lighthouse a11y 0.96): light `text-muted` `#8a948d`→`#646e66` (only WCAG-AA fail, light-only), control-center green washes → `color-mix(in srgb, var(--mw-color-primary) N%, transparent)`, mission/alert copy →16px, single-rail `Overview` documented | Live Lighthouse `color-contrast` failed on the green-wash nav item + status tag; tokenization makes washes retheme into dark. The durable record for this pass lives in a gstack session store kept out of the repo on 2026-09-24 (not vendored here) |
| 2026-09-24 | Phase-3 theme system + a11y close-out: user `auto`/`light`/`dark` toggle (Pinia `useThemeStore`, FOUC-safe pre-paint `data-mw-theme` in `index.html`); Heatmap `minimum-color` rethemed to a per-scheme JS wash so empty cells read empty in both schemes; admission-pill status text fixed to `--mw-color-text-primary` (scheme-flipping `#18211d`/`#f7f8f6`, `14.06:1` light / `12.13:1` dark vs the inverting green wash) | Lighthouse a11y recovered **`0.96`→`1.0`** (Best Practices `1.0`); scheme-aware washes stop the dark-mode contrast inversion; single-source tokens keep the pill and wash from drifting. The durable record for this pass lives in a gstack session store kept out of the repo (admission-pill a11y marked RESOLVED) |
