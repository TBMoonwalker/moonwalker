# Design System — Moonwalker

## Product Context
- **What this is:** Moonwalker is a self-hosted cryptocurrency trading bot with a web dashboard for configuring exchange access, signal sources, DCA behavior, monitoring, and operational safety.
- **Who it's for:** Operators who are running a single Moonwalker instance and need to set it up safely, understand readiness quickly, and recover calmly when something is wrong.
- **Space/industry:** Crypto trading / self-hosted operator tooling / trading automation dashboards.
- **Project type:** Web app / operator dashboard / setup console.

## Aesthetic Direction
- **Direction:** Calm Operator Console
- **Decoration level:** Intentional
- **Mood:** Moonwalker should feel like a careful trading workstation, not a generic admin panel and not a flashy crypto marketing site. The emotional goal is calm control: clear status, obvious next steps, and very little decorative noise competing with operational decisions.
- **Reference sites:** This pass is grounded in Moonwalker's current product and category knowledge rather than external visual research.

## Typography
- **Display/Hero:** `Space Grotesk` — firm and technical enough for operator headlines without tipping into sci-fi theatrics.
- **Body:** `Source Sans 3` — high readability, neutral tone, and strong form legibility for long configuration surfaces.
- **UI/Labels:** `Source Sans 3` semibold — keeps interaction copy calm and direct instead of shouty.
- **Data/Tables:** `IBM Plex Mono` — supports tabular numerals and gives balances, ratios, and diagnostics a trustworthy machine-readable tone.
- **Code:** `Fira Code`
- **Loading:** Google Fonts for `Space Grotesk`, `Source Sans 3`, and `IBM Plex Mono`; `Fira Code` may stay self-hosted or use the existing app asset strategy.
- **Scale:** `12 / 14 / 16 / 20 / 24 / 32 / 40 / 56 px`
  - `12`: tertiary metadata
  - `14`: dense supporting copy
  - `16`: default body and form labels
  - `20`: section titles
  - `24`: card and panel headings
  - `32`: page-level mission titles
  - `40`: first-run gateway headline
  - `56`: marketing/hero use only, rarely needed in product

## Color
- **Approach:** Restrained
- **Primary:** `#1D5C49` — operator green; use for trust, progress, and primary actions.
- **Secondary:** `#B78A2E` — brass accent; use sparingly for “review carefully” moments, never as the dominant page color.
- **Neutrals:** cool-slate range
  - `#F7F8F6` surface base
  - `#ECEFEA` raised surface
  - `#D5DBD5` borders
  - `#8A948D` muted text
  - `#33403A` strong secondary text
  - `#18211D` primary text
- **Semantic:**
  - success `#2E7D5B`
  - warning `#B7791F`
  - error `#B4443F`
  - info `#356D86`
- **Dark mode:** keep the same hierarchy but reduce saturation by roughly 10 to 15 percent and lift contrast through surfaces rather than brighter accents. Dark mode should read as “night operator console,” not neon terminal cosplay.
- **Surface treatment:** gradients belong to page atmosphere or rare emphasis, not to primary working surfaces. Headers, cards, shells, and setup panels should stay flat or near-flat so hierarchy comes from spacing, borders, contrast, and shadow instead of decorative fill.

## Spacing
- **Base unit:** `8px`
- **Density:** Comfortable for setup, compact for advanced
- **Scale:** `2xs(4) xs(8) sm(12) md(16) lg(24) xl(32) 2xl(48) 3xl(64)`

## Layout
- **Approach:** Grid-disciplined
- **Grid:** 12-column desktop, 8-column tablet, 4-column mobile
- **Max content width:** `1200px`
- **Border radius:**
  - `sm: 6px`
  - `md: 10px`
  - `lg: 14px`
  - `full: 9999px`

## Motion
- **Approach:** Minimal-functional
- **Easing:** enter `cubic-bezier(0.2, 0.8, 0.2, 1)`, exit `cubic-bezier(0.4, 0, 1, 1)`, move `cubic-bezier(0.2, 0.7, 0.2, 1)`
- **Duration:** micro `80ms`, short `160ms`, medium `260ms`, long `420ms`

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
reliably know whether they should self-identify as “advanced.”

### First-Run Flow

```text
FIRST RUN
|
|-- Entry Choice
|   |-- Restore existing installation
|   `-- Start new setup
|
|-- If Restore
|   |-- Choose config-only or full backup
|   |-- Perform restore
|   `-- Land in readiness review
|
`-- If Start New
    |-- Choose setup style
    |   |-- Guided setup (recommended)
    |   `-- Full control
    |
    `-- Complete safe dry-run setup
```

### Restore Is Not “Advanced”
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
|   |-- Restore existing installation
|   `-- Start new setup
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
|   |-- readiness state
|   |-- one next action
|   `-- concise evidence
|
|-- Primary Nav
|   |-- Overview
|   `-- Setup
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
- Still anchored on “finish safe dry run,” not on “browse every option”

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
- Primary actions must meet minimum touch target sizes.

## Implementation Guardrails
- Do not reuse the old Settings page mental model inside the new Control Center.
- Do not show all modes at equal weight during first run.
- Do not expose expert toggles inside Guided Setup.
- Do not make restore discoverable only inside Advanced or Utilities during onboarding.
- Do not duplicate normal editable settings between Setup and Advanced.
- Prefer explicit task ownership over component reuse when reuse harms clarity.

## Decisions Log
| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-03-21 | Added repo-level DESIGN.md | Moonwalker had Control Center design intent but no repo-level design source of truth |
| 2026-03-21 | Made first-run begin with `Restore existing installation` vs `Start a new setup` | Intent is clearer and safer than asking the user whether they are “advanced” |
| 2026-03-21 | Made `Guided setup` vs `Full control` the second decision | This preserves expert agency without forking the information architecture |
| 2026-03-21 | Declared restore a first-run entry workflow and a later utility, not an advanced setting | Restore is lifecycle-dependent, not expertise-dependent |
| 2026-03-21 | Declared one-home rule for editable settings | Duplicate fields between Setup and Advanced destroy operator focus |
| 2026-03-21 | Reserved gradients for atmosphere and rare emphasis, not core work surfaces | Flat panels preserve calm hierarchy and keep dark mode from feeling noisy |
