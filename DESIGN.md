---
name: Moonwalker
description: Calm, intent-first operator console for a self-hosted crypto trading bot.
colors:
  primary: "#1d5c49"
  primary-strong: "#18413a"
  primary-soft: "#e3f3ec"
  secondary: "#b78a2e"
  surface-base: "#f7f8f6"
  surface-raised: "#ecefea"
  surface-panel: "#ffffff"
  border: "#d5dbd5"
  text-primary: "#18211d"
  text-secondary: "#33403a"
  text-muted: "#646e66"
  success: "#2e7d5b"
  warning: "#b7791f"
  warning-soft: "#fff8ec"
  error: "#b4443f"
  info: "#356d86"
typography:
  display:
    fontFamily: "Space Grotesk, sans-serif"
    fontSize: "clamp(1.5rem, 2vw, 2.25rem)"
    fontWeight: 500
    lineHeight: 1.2
    letterSpacing: "normal"
  body:
    fontFamily: "Source Sans 3, sans-serif"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: "normal"
  label:
    fontFamily: "Source Sans 3, sans-serif"
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
  button-primary-hover:
    backgroundColor: "{colors.success}"
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
  mission-panel:
    backgroundColor: "{colors.primary-soft}"
    textColor: "{colors.text-primary}"
    typography: "display"
    rounded: "{rounded.md}"
    padding: "14px 16px"
  dashboard-card:
    backgroundColor: "{colors.surface-panel}"
    textColor: "{colors.text-primary}"
    typography: "body"
    rounded: "{rounded.md}"
    padding: "16px"
  status-tag:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.surface-panel}"
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

**Creative North Star: "The Calm Operator Console"**

Moonwalker is a careful trading workstation, not a generic admin panel and not a flashy crypto marketing site. The emotional goal is calm control: clear status, obvious next steps, and very little decorative noise competing with operational decisions. Hierarchy comes from spacing, borders, contrast, and a single soft card shadow — not from decorative fill. Working surfaces stay flat or near-flat; gradients are reserved for page atmosphere and rare emphasis, which keeps dark mode reading as a night operator console rather than neon-terminal cosplay.

The console asks the operator for intent before exposing breadth. First run does not begin with a mode strip or a dense settings grid; it begins with one intent question (restore an existing installation, or start a new setup) and then a setup-style choice (guided or full control). Each editable setting has exactly one canonical home, readiness gates stand between dry run and live trading, and the dashboard optimizes for calm control and recoverable outcomes rather than marketing or feature density.

The palette is restrained: one operator-green primary carries trust, progress, and primary action; a brass accent is used sparingly only for "review carefully" moments; semantic success/warning/error/info tones mark readiness and risk. Tabular data earns a monospace face, and the type scale steps in an even, calm rhythm so dense configuration surfaces stay legible.

**Key Characteristics:**

- Calm operator console: status and next action first, decoration second.
- One operator-green primary; brass used sparingly as a review accent.
- Flat, bordered, single-shadow surfaces; gradients reserved for atmosphere.
- Intent-first flow: one question, one active task, no equal-weight mode strip.
- Even type scale (12/14/16/20/24/32/40/56) with a monospace data face.

## Colors

A restrained, cool-slate palette built around a single operator-green primary, with a scarce brass review accent and a small semantic set for readiness and risk.

### Primary
- **Operator Green** (#1d5c49): The trust color. Primary actions (Save changes, Go live, Restore), progress, and "ready" states. The single voice of the console.
- **Deep Operator Green** (#18413a): Pressed/active state of primary buttons; used for focus rings and inset selection.
- **Operator Green Soft** (#e3f3ec): Faint green wash behind mission and admission bands — depth without a shadow.
- **Brass Review Accent** (#b78a2e): The scarce secondary. "Review carefully" moments only (readiness gates, pending attention). Never the dominant page color.

### Neutral
- **Console Base** (#f7f8f6): Page ground. Cool, slightly green-tinted off-white.
- **Raised Surface** (#ecefea): Slightly lifted region ground.
- **Raised Panel** (#ffffff): Card and form-field ground; the resting working surface.
- **Border** (#d5dbd5): Default 1px border and divider.
- **Primary Text** (#18211d): Headings and primary copy.
- **Secondary Text** (#33403a): Body copy and form labels.
- **Muted Text** (#646e66): Tertiary metadata, kickers, placeholders. Light-mode value; dark mode lifts it via `rgba(213, 219, 213, 0.72)` (6.3:1). The light value was darkened 2026-09-23 from `#8a948d` to clear WCAG AA (4.5:1) — `#8a948d` measured 2.94:1 on the console base, the only AA failure on the surface.

### Semantic
- **Success Green** (#2e7d5b): Ready / healthy / passing states; also primary button hover.
- **Warning Amber** (#b7791f): Needs attention without being fatal; its soft ground is #fff8ec.
- **Error Red** (#b4443f): Failed / blocking readiness gate.
- **Info Blue** (#356d86): Neutral informational notes.

### Named Rules
**The One Voice Rule.** Operator green is the single primary; the brass secondary is a scarce "review carefully" accent, used on no more than ~10% of any screen. Its rarity is the point.
**The Night-Console Rule.** Dark mode keeps the same hierarchy, lowers saturation by ~10–15%, and lifts contrast through surfaces rather than brighter accents. It reads as a night operator console, not neon-terminal cosplay.

## Typography

**Display Font:** Space Grotesk (with system sans fallback)
**Body Font:** Source Sans 3 (with "Segoe UI", sans-serif fallback)
**Data/Mono Font:** IBM Plex Mono (with "SFMono-Regular", monospace fallback)
**Code Font:** Fira Code

**Character:** Firm, technical, and human. Space Grotesk gives operator headlines a precise, slightly engineered tone without sci-fi theatrics; Source Sans 3 keeps dense configuration copy calm and direct; IBM Plex Mono gives balances, ratios, and diagnostics a trustworthy, tabular-numeral, machine-readable voice.

### Hierarchy
- **Display** (500, clamp(1.5rem–2.25rem) / ~32–40px, 1.2): Page-level mission titles, first-run gateway headlines, section titles. Space Grotesk.
- **Title** (450, 20–24px, 1.25): Card and panel headings. Space Grotesk.
- **Body** (400, 16px, 1.5, max 72ch): Default reading copy and form labels. Source Sans 3.
- **Label** (600, 14px, 1.2, tracked): UI controls, kickers, status tags. Source Sans 3 semibold.
- **Mono / Data** (450, 14px, 1.4): Balances, ratios, diagnostics, tabular figures. IBM Plex Mono with tabular numerals.

### Scale
`12 / 14 / 16 / 20 / 24 / 32 / 40 / 56 px` — even, calm rhythm. 12 tertiary metadata · 14 dense supporting copy · 16 default body and form labels · 20 section titles · 24 card/panel headings · 32 page-level mission titles · 40 first-run gateway headline · 56 marketing/hero use only, rarely needed in product.

### Named Rules
**The Data-Gets-Mono Rule.** Any figure that is money, ratio, or diagnostic (balances, uPNL, ratios, order sizes) is set in IBM Plex Mono with tabular numerals; prose stays in Source Sans 3.

## Layout

Grid-disciplined and intent-segmented. A 12-column desktop grid collapses to 8-column tablet and 4-column mobile within a `1200px` max content width. The Control Center is not a static tab layout — it is a lifecycle segment: before readiness it shows only the setup surface (entry gateway or one active setup task); after safe dry-run readiness it unlocks Overview as the default home, Advanced as the full-density tuning surface, and Utilities for operational actions. Density is comfortable for setup and compact for advanced tuning. Spacing rhythm is an 8px base with the scale `2xs(4) / xs(8) / sm(12) / md(16) / lg(24) / xl(32) / 2xl(48) / 3xl(64)`.

**The Intent-Before-Breadth Rule.** First run opens with one intent question, not a mode strip or a wall of fields; breadth is revealed only as far as the chosen intent requires.
**The One-Home Rule.** Every editable configuration field has exactly one canonical visible home — essentials in Setup, expert tuning in Advanced, status in Overview, operational actions in Utilities. Deeper tuning *extends* an area; it never restates the same field.
**The Single-Rail-Overview Rule.** After safe dry-run readiness, `Overview` renders as a single calm column (`grid-template-columns: 1fr`) rather than spreading status across the 12-column grid. This is an override *by intent* — a night-console reading column — not an omission; `Advanced` is where density and the full grid belong. Documented 2026-09-23 (plan review D6).

## Elevation & Depth

Shadows are rare and calm. Working surfaces are flat or near-flat at rest; hierarchy is carried primarily by spacing, borders, contrast, and a single soft card shadow. Two shadow tokens exist: `ambient-soft` (`0 12px 28px rgba(24, 33, 29, 0.08)`) for emphasis surfaces (mission/admission bands) and `card` (`0 10px 24px rgba(24, 33, 29, 0.05)`) as the default panel resting elevation. In dark mode the same shadows deepen (`0 12px 28px rgba(0,0,0,0.28)` / `0 10px 24px rgba(0,0,0,0.22)`) to preserve legibility on dark surfaces.

### Shadow Vocabulary
- **Card** (`0 10px 24px rgba(24, 33, 29, 0.05)`): Default resting elevation for dashboard cards, subpanels, and mission panels.
- **Ambient Soft** (`0 12px 28px rgba(24, 33, 29, 0.08)`): Diffuse ambient lift for emphasis surfaces where a touch more depth is warranted.

### Named Rules
**The Flat-By-Default Rule.** Headers, cards, shells, and setup panels are flat at rest; a shadow appears only as a response to state (emphasis band, hover elevation). Gradients are reserved for page atmosphere and rare emphasis, never for primary working surfaces.

## Shapes

Soft, consistent corners from a single radius family — `sm` 6px, `md` 10px, `lg` 14px, `full` 9999px for pills — over 1px solid borders in the neutral border tone (#d5dbd5). There is no clipping, no hard-cut geometry, and no bevel; the form language is rounded, bordered, and restrained. Status tags and similar pills use `full` (9999px); cards and fields use `md` (10px); compact chips use `sm` (6px).

**The Single-Radius-Voice Rule.** Every surface draws from the one radius scale at one step; no surface invents an ad-hoc radius. A mismatched corner reads as noise.

## Components

### Buttons
- **Shape:** Gently rounded (10px, `md`), 9px × 18px padding, 14px semibold label.
- **Primary:** Operator-green fill (#1d5c49) with light text (#f7f8f6); hover to success green (#2e7d5b) with a 1px lift; active to deep operator green (#18413a). Decisive, the dominant action.
- **Secondary:** Raised panel ground with operator-green text and a faint green border; hover fills a 6% green wash.
- **Focus:** 2px operator-green ring, 2px offset — lift by ring, never a hard outline.

### Status Tags (chips)
- **Style:** Full-radius pill (9999px), 4px × 10px padding, 14px semibold. Success wears operator green on light text; info wears info blue; warning wears a 14% brass wash with brass text.
- **State:** Tone is set by semantic color, not by a selected/unselected toggle.
- **Exception — admission pill:** the admission strip's `.admission-pill` is the one chip whose *text* does not follow the tone. Its green wash inverts polarity per scheme (pale green in light, near-black green in dark), so no single fixed green text can clear 4.5:1 on both; instead its `.n-tag__content` uses the already scheme-flipping `--mw-color-text-primary` (`#18211d` / `#f7f8f6`; `14.06:1` / `12.13:1`). Scoped to `.admission-strip.is-open`, so warning/error pills keep their own colours. Added 2026-09-24 with the a11y `0.96`→`1.0` recovery.

### Cards / Containers
- **Corner Style:** `md` (10px).
- **Background:** Raised panel (#ffffff) for working surfaces; faint operator-green wash (#e3f3ec) for the mission panel.
- **Shadow Strategy:** Resting `card` shadow by default; `ambient-soft` for emphasis.
- **Border:** 1px neutral border (#d5dbd5).
- **Internal Padding:** `md` (16px) standard, 14px × 16px for the mission panel.

### Inputs / Fields
- **Style:** 1px neutral border (#d5dbd5), raised-panel ground, `md` (10px) radius, 9px × 12px padding, 16px body text.
- **Focus:** Border shifts to operator green with a 3px 14% green glow ring; placeholder in muted text.
- **Label:** 14px semibold secondary text, stacked above with a 6px gap.

### Navigation
- **Style:** Horizontal header menu; items are rounded (10px), 8px × 12px padding, 14px label.
- **States:** Default secondary text; hover to a 6% green wash; active to an 18% green wash with an inset 1px green ring and 500 weight.

### Signature Components
- **Mission Panel:** The signature surface. Readiness state + one next action + concise evidence, on a faint operator-green wash with a resting card shadow.
- **Admission Strip:** A signaled band (info or warning) carrying one readiness or readiness-gate message with a leading status pill.

## Do's and Don'ts

### Do:
- **Do** ask the operator for intent before exposing breadth.
- **Do** give every editable setting exactly one canonical home.
- **Do** prefer explicit task ownership over component reuse when reuse harms clarity.
- **Do** keep working surfaces flat and reserve gradients for page atmosphere and rare emphasis.
- **Do** use intent-based, consequence-aware, state-first copy with no self-labeling.
- **Do** set money, ratio, and diagnostic figures in IBM Plex Mono with tabular numerals.
- **Do** lift focus and selection with a 2px operator-green ring, not a hard outline.

### Don't:
- **Don't** reuse the old Settings page mental model inside the new Control Center.
- **Don't** show all modes at equal weight during first run.
- **Don't** expose expert toggles inside Guided Setup.
- **Don't** make restore discoverable only inside Advanced or Utilities during onboarding.
- **Don't** duplicate normal editable settings between Setup and Advanced.
- **Don't** use self-labeling or category terms like "Configuration", "Beginner", or "Advanced user".
- **Don't** apply gradients to primary working surfaces (headers, cards, shells, setup panels).

---

<!-- The sections below preserve Moonwalker's incumbent operator-UX, Control Center IA,
     screen-level guidance, copy rules, accessibility, guardrails, and live-measured baseline.
     They are project-specific extras kept alongside the canonical eight sections above. -->

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
- Do not show `Overview`, `Advanced`, and `Utilities` as equal first-run peers.
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
- Unlock `Overview` as the default home.
- Unlock `Advanced` as the full-density tuning surface.
- Keep `Utilities` available for operational tasks like backup/restore and connectivity checks.

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
CONTROL CENTER
|
|-- Mission Panel
|    |-- readiness state
|    |-- one next action
|    `-- concise evidence
|
|-- Primary Nav
|    |-- Overview
|    `-- Setup
|
`-- Secondary Nav
     |-- Advanced
     `-- Utilities
```

### One-Home Rule
Every configuration field gets exactly one canonical visible home.

- Essentials live in `Setup`
- Expert tuning lives in `Advanced`
- Status lives in `Overview`
- Operational actions live in `Utilities`

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
- This screen should be visually quieter than Overview and more decisive than Settings.

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

### 5. Overview After Readiness
- Calm status first
- One next recommended action
- Evidence row for recent changes or warnings
- Setup remains reachable but no longer dominates

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
- Avoid category terms like `Configuration` unless needed for advanced surfaces

## Accessibility Requirements
- The first-run entry choice must be fully keyboard navigable and understandable without color.
- Guided task expansion must preserve clear focus order.
- Revealing expert controls inline must move focus predictably and announce the change.
- Restore outcomes and readiness review states must use ARIA live regions.
- Primary actions must meet minimum touch target sizes (44px).

## Implementation Guardrails
- Do not reuse the old Settings page mental model inside the new Control Center.
- Do not show all modes at equal weight during first run.
- Do not expose expert toggles inside Guided Setup.
- Do not make restore discoverable only inside Advanced or Utilities during onboarding.
- Do not duplicate normal editable settings between Setup and Advanced.
- Prefer explicit task ownership over component reuse when reuse harms clarity.

## Motion
- **Approach:** Minimal-functional
- **Easing:** enter `cubic-bezier(0.2, 0.8, 0.2, 1)`, exit `cubic-bezier(0.4, 0, 1, 1)`, move `cubic-bezier(0.2, 0.7, 0.2, 1)`
- **Duration:** micro `80ms`, short `160ms`, medium `260ms`, long `420ms`

## Verified Baseline (Live-Measured, 2026-06-05)

These values were extracted from the running site at http://192.168.6.5:8160/stats — not from source code. They confirm what actually renders.

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

### Known Deviations
_Re-checked 2026-09-24 against the tokenized, a11y-1.0 build by source-truth grep — no live pass. An absent override or fix means the deviation is still open; an explicit source value means it is resolved there._

| Issue | Current | Should Be | Severity |
|-------|---------|-----------|----------|
| Body font size | **Resolved at document scope.** Base document body is `16px` (`base.css` `body`, line 149); the mission/alert copy band is `16px` (T4, 2026-09-23). `14px` remains on component labels (buttons/tags/nav) and dense ledger table cells (`.n-data-table --n-font-size: 14px`) — documented intent in this system, not a deviation. | `16px` per scale (document scope) | Resolved (base) · informational (component labels by design) |
| Pagination touch targets | **Resolved (2026-09-24).** `44px` now covers every paged surface: stats-table pagination (`.ledger-panel`/`.ai-trust-card`, `StatisticsView.vue:1200`, ≤767px), control-center pages (`ControlCenterView.vue:643`, ≤767px), mobile **row-action** buttons (`TradesView.vue:683`, ≤520px), and — added this arc — the three paged trade feeds (Open/Closed/Unsellable), whose Naive `NDataTable` pagination renders inside `.ledger-panel` in `TradesView.vue` (new `:deep(.n-pagination-item)` rule at the foot of its `@media(max-width:520px)` block, mirroring `StatisticsView.vue`). Live CSSOM-verified that day: the rule is loaded, gated to `≤520px`, inert at `>520px` (an injected test item measured 0px wide at 800px), and its selector specificity (`0,0,3`) beats Naive's base `.n-pagination-item` (`0,0,1`), so at 375px the feed items resolve to 44×44px. (A 375px eyeball is skipped — this browser toolset has no viewport emulation — but the result is deterministic from the gated high-specificity rule; CI-built into `TradesView-*.css`.) | `44x44px` minimum on mobile | **Resolved** (all paged surfaces: stats, control-center, row-actions, 3 trade feeds) |
| Mobile text truncation | **Open (unverified 375px).** Re-audited 2026-09-24: `text-overflow:ellipsis` **does** exist in source — on the ledger symbol cell `.trade-symbol-main` (`TradesView.vue`, at both the `≤767px` gate, line 604, and the `≤520px` gate, line 661) — so the earlier "no ellipsis anywhere" note was a false negative (a `*.css`-only grep never looked at the `.vue` scoped `<style>` blocks). Responsive guards exist (`@media(max-width:767px)` + `520px` in `main.css`, `white-space:normal` tab-wrap at ≤520px). A live clip-scan (`scrollWidth>clientWidth`) on a data-less shell at 800px returned **0 candidates** (desktop has room); the 2026-06-05 `"les mo"` @375px case cannot be reproduced without viewport emulation (absent in this browser toolset) plus live trade data, so it stays open pending a device-emulated, data-fed re-check. | Full text with ellipsis on narrow cells | **Low** (open; re-check on a device-emulated, data-fed session) |

### Performance Baseline
| Metric | Value |
|--------|-------|
| TTFB | 10ms |
| DOM Ready | 70ms |
| Full Load | 72ms |

### Accessibility Score
- **Re-measured 2026-09-24: Lighthouse Accessibility `1.0`** (was `0.96` on 2026-09-23); **Best Practices `1.0`**. Vehicle: fresh production build on a throwaway loopback `:4173` — a data-independent shell, so the score reflects theme + a11y, not live market data.
- Drivers of the `0.96`→`1.0` recovery: (a) the admission-pill status text set to `--mw-color-text-primary` — scheme-flipping `#18211d` (light) / `#f7f8f6` (dark), measured `14.06:1` light / `12.13:1` dark, both clear 4.5:1 AA against the green wash that inverts polarity per scheme; (b) `text-muted` `#8a948d`→`#646e66` (2026-09-23).
- Remaining Lighthouse flags are `meta-description` / `robots.txt` — SEO metadata, **not** accessibility — so no a11y work remains.

## Decisions Log
| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-03-21 | Added repo-level DESIGN.md | Moonwalker had Control Center design intent but no repo-level design source of truth |
| 2026-03-21 | Made first-run begin with `Restore existing installation` vs `Start a new setup` | Intent is clearer and safer than asking the user whether they are "advanced" |
| 2026-03-21 | Made `Guided setup` vs `Full control` the second decision | This preserves expert agency without forking the information architecture |
| 2026-03-21 | Declared restore a first-run entry workflow and a later utility, not an advanced setting | Restore is lifecycle-dependent, not expertise-dependent |
| 2026-03-21 | Declared one-home rule for editable settings | Duplicate fields between Setup and Advanced destroy operator focus |
| 2026-03-21 | Reserved gradients for atmosphere and rare emphasis, not core work surfaces | Flat panels preserve calm hierarchy and keep dark mode from feeling noisy |
| 2026-06-05 | Added verified baseline section | Live-measured values confirm design system compliance; deviations tracked for remediation |
| 2026-09-12 | Canonicalized DESIGN.md to the 8-section format with YAML frontmatter tokens | Tokens extracted from `frontend/src/assets/base.css` `--mw-*` custom properties; incumbent operator-UX content preserved as extra sections |
| 2026-09-23 | Control-center design review (live Lighthouse a11y 0.96): light `text-muted` `#8a948d`→`#646e66` (only WCAG-AA fail, light-only), control-center green washes → `color-mix(in srgb, var(--mw-color-primary) N%, transparent)`, mission/alert copy →16px, single-rail `Overview` documented | Live Lighthouse `color-contrast` failed on the green-wash nav item + status tag; tokenization makes washes retheme into dark. the durable record for this pass lives in a gstack session store kept out of the repo on 2026-09-24 (not vendored here) |
| 2026-09-24 | Phase-3 theme system + a11y close-out: user `auto`/`light`/`dark` toggle (Pinia `useThemeStore`, FOUC-safe pre-paint `data-mw-theme` in `index.html`); Heatmap `minimum-color` rethemed to a per-scheme JS wash so empty cells read empty in both schemes; admission-pill status text fixed to `--mw-color-text-primary` (scheme-flipping `#18211d`/`#f7f8f6`, `14.06:1` light / `12.13:1` dark vs the inverting green wash) | Lighthouse a11y recovered **`0.96`→`1.0`** (Best Practices `1.0`); scheme-aware washes stop the dark-mode contrast inversion; single-source tokens keep the pill and wash from drifting. the durable record for this pass lives in a gstack session store kept out of the repo (admission-pill a11y marked RESOLVED) |
