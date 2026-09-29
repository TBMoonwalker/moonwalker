/**
 * Theme tokens — single source of truth for Moonwalker's design-system palette.
 *
 * Two layers mirror these values at runtime:
 *   1. Naive UI `themeOverrides` (consumed by `App.vue` via `n-config-provider`).
 *   2. The CSS custom properties in `assets/base.css` (`--mw-*`, `--color-*`).
 *
 * A build-time drift guard (`tests-vitest/themeDrift.test.ts`) parses `base.css`
 * and asserts both layers stay in agreement, so changing a token in one layer
 * fails CI until the other is updated in lockstep. This is what caught the light
 * `textColor3` vs `--mw-color-text-muted` drift introduced by the T8 AA fix.
 *
 * Editing a token here is the canonical action; the guard then forces either
 * `base.css` or the Naive override to be updated to match.
 */

export type ColorScheme = "light" | "dark"

/** Naive UI `themeOverrides` fragments for one scheme (`common` / `Tabs` / `Button`). */
export interface NaiveTokenSet {
   common: Record<string, string>
   Tabs: Record<string, string>
   Button: Record<string, string>
}

/**
 * The CSS custom properties a scheme declares. `light` is the full `:root`
 * baseline; `dark` holds only the values that `@media (prefers-color-scheme: dark)`
 * overrides. `getEffectiveCss` folds dark over light to reproduce the cascade.
 */
export type CssTokenMap = Record<string, string>

export interface ThemeTokens {
   /** Naive overrides consumed by `App.vue`. */
   naive: NaiveTokenSet
   /** CSS `--mw-*` / `--color-*` values mirrored by `assets/base.css`. */
   css: CssTokenMap
}

const LIGHT_MUTED = "#65656f"

export const themeTokens = {
   light: {
      naive: {
         common: {
            fontFamily: "'General Sans', 'Source Sans 3', sans-serif",
            fontFamilyMono: "'IBM Plex Mono', 'SFMono-Regular', monospace",
            fontWeightStrong: "600",
            primaryColor: "#276b47",
            primaryColorHover: "#2f8054",
            primaryColorPressed: "#205a3b",
            primaryColorSuppl: "#276b47",
            infoColor: "#356d86",
            successColor: "#157651",
            warningColor: "#995d14",
            errorColor: "#b4443f",
            bodyColor: "#f5f5f7",
            baseColor: "#ffffff",
            cardColor: "#ffffff",
            modalColor: "#ffffff",
            popoverColor: "#ffffff",
            borderColor: "#d9d9e0",
            dividerColor: "#d9d9e0",
            textColorBase: "#19191d",
            textColor1: "#19191d",
            textColor2: "#45454e",
            // T8 (2026-09-23): light muted text must clear WCAG AA (4.97:1).
            // Naive's tertiary text tracks the CSS --mw-color-text-muted token.
            textColor3: LIGHT_MUTED,
            borderRadius: "10px",
            borderRadiusSmall: "6px",
         },
         Tabs: {
            tabTextColorLine: "#45454e",
            tabTextColorActiveLine: "#276b47",
            tabTextColorHoverLine: "#205a3b",
            tabTextColorDisabledLine: LIGHT_MUTED,
            barColor: "#276b47",
            tabFontWeight: "450",
            tabFontWeightActive: "500",
         },
         Button: {
            textColorPrimary: "#ffffff",
            textColorHoverPrimary: "#ffffff",
            textColorPressedPrimary: "#ffffff",
            textColorFocusPrimary: "#ffffff",
            fontWeightStrong: "500",
         },
     },
      css: {
         "--mw-font-display": "'General Sans', 'Source Sans 3', sans-serif",
         "--mw-font-body": "'General Sans', 'Source Sans 3', sans-serif",
         "--mw-font-mono": "'IBM Plex Mono', monospace",
         "--mw-color-primary": "#276b47",
         "--mw-color-primary-strong": "#205a3b",
         "--mw-color-primary-soft": "#e5f3e8",
         "--mw-color-secondary": "#995d14",
         "--mw-color-surface-base": "#f5f5f7",
         "--mw-color-surface-raised": "#ededf0",
         "--mw-color-surface-panel": "#ffffff",
         "--mw-color-border": "#d9d9e0",
         "--mw-color-border-strong": "#bcbcc6",
         "--mw-color-text-primary": "#19191d",
         "--mw-color-text-secondary": "#45454e",
         "--mw-color-text-muted": LIGHT_MUTED,
         "--mw-color-success": "#157651",
         "--mw-color-warning": "#995d14",
         "--mw-color-warning-soft": "#fff2dd",
         "--mw-color-error": "#b4443f",
         "--mw-color-info": "#356d86",
         "--mw-surface-card": "#ffffff",
         "--mw-surface-card-muted": "#f6f6f8",
         "--mw-surface-card-subtle": "#f5f5f7",
         "--mw-surface-card-success": "#e7f3eb",
         "--mw-surface-card-warning": "#fff2dd",
         "--mw-surface-header": "#ffffff",
         "--mw-surface-shell": "#ffffff",
         "--mw-surface-mission": "#f6f6f8",
         "--mw-surface-active": "color-mix(in srgb, var(--mw-color-primary) 8%, transparent)",
         "--mw-control-readonly-border": "color-mix(in srgb, var(--mw-color-primary) 22%, transparent)",
         "--mw-control-readonly-bg": "var(--mw-color-primary-soft)",
         "--mw-control-readonly-text": "var(--mw-color-primary-strong)",
         "--mw-shadow-soft": "0 8px 22px rgba(25, 25, 29, 0.07)",
         "--mw-shadow-card": "none",
         "--mw-focus-ring":
            "2px solid color-mix(in srgb, var(--mw-color-primary) 70%, transparent)",
         "--mw-focus-offset": "2px",
         "--mw-radius-sm": "6px",
         "--mw-radius-md": "10px",
         "--mw-radius-lg": "14px",
         "--mw-content-width": "1500px",
         "--color-background": "var(--mw-color-surface-base)",
         "--color-background-soft": "var(--mw-color-surface-raised)",
         "--color-background-mute": "var(--mw-color-surface-panel)",
         "--color-border": "#d9d9e0",
         "--color-border-hover": "var(--mw-color-border-strong)",
         "--color-heading": "var(--mw-color-text-primary)",
         "--color-text": "var(--mw-color-text-secondary)",
     },
  },
  dark: {
     naive: {
        common: {
           fontFamily: "'General Sans', 'Source Sans 3', sans-serif",
           fontFamilyMono: "'IBM Plex Mono', 'SFMono-Regular', monospace",
           fontWeightStrong: "600",
           primaryColor: "#9cdb73",
           primaryColorHover: "#b5e68f",
           primaryColorPressed: "#7ec154",
           primaryColorSuppl: "#9cdb73",
           infoColor: "#356d86",
           successColor: "#69d2aa",
           warningColor: "#efb46c",
           errorColor: "#fa8494",
           bodyColor: "#19191d",
           baseColor: "#222227",
           cardColor: "#222227",
           modalColor: "#222227",
           popoverColor: "#222227",
           borderColor: "#34343b",
           dividerColor: "#34343b",
           textColorBase: "#f5f5f7",
           textColor1: "#f5f5f7",
           textColor2: "#c7c7d0",
           textColor3: "#a4a4af",
           borderRadius: "10px",
           borderRadiusSmall: "6px",
         },
         Tabs: {
            tabTextColorLine: "#c7c7d0",
            tabTextColorActiveLine: "#9cdb73",
            tabTextColorHoverLine: "#b5e68f",
            tabTextColorDisabledLine: "#a4a4af",
            barColor: "#9cdb73",
            tabFontWeight: "450",
            tabFontWeightActive: "500",
         },
         Button: {
            textColorPrimary: "#172017",
            textColorHoverPrimary: "#172017",
            textColorPressedPrimary: "#172017",
            textColorFocusPrimary: "#172017",
            fontWeightStrong: "500",
         },
     },
      // Dark is an OVERRIDE set. getEffectiveCss folds it over light.
      css: {
         "--mw-color-primary": "#9cdb73",
         "--mw-color-primary-strong": "#7ec154",
         "--mw-color-primary-soft": "rgba(156, 219, 115, 0.12)",
         "--mw-color-surface-base": "#19191d",
         "--mw-color-surface-raised": "#17171b",
         "--mw-color-surface-panel": "#222227",
         "--mw-color-border": "#34343b",
         "--mw-color-border-strong": "#50505a",
         "--mw-color-text-primary": "#f5f5f7",
         "--mw-color-text-secondary": "#c7c7d0",
         "--mw-color-text-muted": "#a4a4af",
         "--mw-color-success": "#69d2aa",
         "--mw-color-warning": "#efb46c",
         "--mw-color-warning-soft": "#493421",
         "--mw-color-error": "#fa8494",
         "--mw-color-info": "#7cbeda",
         "--mw-surface-card": "#222227",
         "--mw-surface-card-muted": "#28282e",
         "--mw-surface-card-subtle": "#19191d",
         "--mw-surface-card-success": "#1d3d34",
         "--mw-surface-card-warning": "#493421",
         "--mw-surface-header": "#19191d",
         "--mw-surface-shell": "#222227",
         "--mw-surface-mission": "#28282e",
         "--mw-surface-active": "color-mix(in srgb, var(--mw-color-primary) 30%, transparent)",
         "--mw-control-readonly-border": "var(--mw-color-border-strong)",
         "--mw-control-readonly-bg": "color-mix(in srgb, var(--mw-color-primary) 34%, transparent)",
         "--mw-control-readonly-text": "var(--mw-color-text-primary)",
         "--mw-shadow-soft": "0 8px 22px rgba(0, 0, 0, 0.2)",
         "--mw-shadow-card": "none",
         "--color-background": "var(--mw-color-surface-base)",
         "--color-background-soft": "var(--mw-color-surface-raised)",
         "--color-background-mute": "var(--mw-color-surface-panel)",
         "--color-border": "#34343b",
         "--color-border-hover": "var(--mw-color-border-strong)",
         "--color-heading": "var(--mw-color-text-primary)",
         "--color-text": "var(--mw-color-text-secondary)",
     },
  },
} satisfies Record<ColorScheme, ThemeTokens>

/** Fold dark override values over the light baseline for a single scheme. */
export function getEffectiveCss(scheme: ColorScheme): CssTokenMap {
   const light = themeTokens.light.css
   if (scheme === "dark") {
      return { ...light, ...themeTokens.dark.css }
      }
  return { ...light }
}

/**
 * Semantic Naive-token ↔ CSS-variable pairs the guard enforces in lockstep, per
 * scheme. Keys intentionally exclude the values that legitimately differ between
 * layers (e.g. `baseColor`/`cardColor` vs `--mw-color-surface-*`, and the font
 * stacks, whose Naive fallbacks differ from the CSS var).
 */
export const NAIVE_CSS_PAIRS = [
   { naive: "primaryColor", css: "--mw-color-primary" },
   { naive: "primaryColorPressed", css: "--mw-color-primary-strong" },
   { naive: "textColorBase", css: "--mw-color-text-primary" },
   { naive: "textColor1", css: "--mw-color-text-primary" },
   { naive: "textColor2", css: "--mw-color-text-secondary" },
   { naive: "textColor3", css: "--mw-color-text-muted" },
   { naive: "borderColor", css: "--mw-color-border" },
] as const
