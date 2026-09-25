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

const NAVY_MUTED = "#646e66"

export const themeTokens = {
   light: {
      naive: {
         common: {
            fontFamily: "'Source Sans 3', 'Segoe UI', sans-serif",
            fontFamilyMono: "'IBM Plex Mono', 'SFMono-Regular', monospace",
            fontWeightStrong: "600",
            primaryColor: "#1d5c49",
            primaryColorHover: "#2e7d5b",
            primaryColorPressed: "#18413a",
            primaryColorSuppl: "#1d5c49",
            infoColor: "#356d86",
            successColor: "#2e7d5b",
            warningColor: "#b7791f",
            errorColor: "#b4443f",
            bodyColor: "#f7f8f6",
            baseColor: "#ffffff",
            cardColor: "#f4f6f2",
            modalColor: "#f5f7f4",
            popoverColor: "#f5f7f4",
            borderColor: "#d5dbd5",
            dividerColor: "rgba(24, 33, 29, 0.08)",
            textColorBase: "#18211d",
            textColor1: "#18211d",
            textColor2: "#33403a",
            // T8 (2026-09-23): light muted text must clear WCAG AA (4.97:1).
            // Naive's tertiary text tracks the CSS --mw-color-text-muted token.
            textColor3: NAVY_MUTED,
            borderRadius: "10px",
            borderRadiusSmall: "6px",
         },
         Tabs: {
            tabTextColorLine: "#33403a",
            tabTextColorActiveLine: "#1d5c49",
            tabTextColorHoverLine: "#18413a",
            tabTextColorDisabledLine: NAVY_MUTED,
            barColor: "#1d5c49",
            tabFontWeight: "450",
            tabFontWeightActive: "500",
         },
         Button: {
            textColorPrimary: "#f7f8f6",
            textColorHoverPrimary: "#f7f8f6",
            textColorPressedPrimary: "#f7f8f6",
            textColorFocusPrimary: "#f7f8f6",
            fontWeightStrong: "500",
         },
     },
      css: {
         "--mw-font-display": "'Space Grotesk', sans-serif",
         "--mw-font-body": "'Source Sans 3', sans-serif",
         "--mw-font-mono": "'IBM Plex Mono', monospace",
         "--mw-color-primary": "#1d5c49",
         "--mw-color-primary-strong": "#18413a",
         "--mw-color-primary-soft": "#e3f3ec",
         "--mw-color-secondary": "#b78a2e",
         "--mw-color-surface-base": "#f7f8f6",
         "--mw-color-surface-raised": "#ecefea",
         "--mw-color-surface-panel": "#ffffff",
         "--mw-color-border": "#d5dbd5",
         "--mw-color-border-strong": "rgba(24, 33, 29, 0.14)",
         "--mw-color-text-primary": "#18211d",
         "--mw-color-text-secondary": "#33403a",
         "--mw-color-text-muted": NAVY_MUTED,
         "--mw-color-success": "#2e7d5b",
         "--mw-color-warning": "#b7791f",
         "--mw-color-warning-soft": "#fff8ec",
         "--mw-color-error": "#b4443f",
         "--mw-color-info": "#356d86",
         "--mw-surface-card": "rgba(255, 255, 255, 0.94)",
         "--mw-surface-card-muted": "rgba(247, 248, 246, 0.92)",
         "--mw-surface-card-subtle": "rgba(247, 248, 246, 0.86)",
         "--mw-surface-card-success": "rgba(227, 243, 236, 0.9)",
         "--mw-surface-card-warning": "rgba(255, 248, 236, 0.94)",
         "--mw-surface-header": "rgba(255, 255, 255, 0.9)",
         "--mw-surface-shell": "rgba(255, 255, 255, 0.88)",
         "--mw-surface-mission": "rgba(227, 243, 236, 0.72)",
         "--mw-surface-active": "color-mix(in srgb, var(--mw-color-primary) 8%, transparent)",
         "--mw-control-readonly-border": "color-mix(in srgb, var(--mw-color-primary) 22%, transparent)",
         "--mw-control-readonly-bg": "var(--mw-color-primary-soft)",
         "--mw-control-readonly-text": "var(--mw-color-primary-strong)",
         "--mw-shadow-soft": "0 12px 28px rgba(24, 33, 29, 0.08)",
         "--mw-shadow-card": "0 10px 24px rgba(24, 33, 29, 0.05)",
         "--mw-focus-ring":
            "2px solid color-mix(in srgb, var(--mw-color-primary) 70%, transparent)",
         "--mw-focus-offset": "2px",
         "--mw-radius-sm": "6px",
         "--mw-radius-md": "10px",
         "--mw-radius-lg": "14px",
         "--mw-content-width": "1200px",
         "--color-background": "var(--mw-color-surface-base)",
         "--color-background-soft": "var(--mw-color-surface-raised)",
         "--color-background-mute": "var(--mw-color-surface-panel)",
         "--color-border": "rgba(24, 33, 29, 0.08)",
         "--color-border-hover": "var(--mw-color-border-strong)",
         "--color-heading": "var(--mw-color-text-primary)",
         "--color-text": "var(--mw-color-text-secondary)",
     },
  },
  dark: {
     naive: {
        common: {
           fontFamily: "'Source Sans 3', 'Segoe UI', sans-serif",
           fontFamilyMono: "'IBM Plex Mono', 'SFMono-Regular', monospace",
           fontWeightStrong: "600",
           primaryColor: "#245f4e",
           primaryColorHover: "#2e7d5b",
           primaryColorPressed: "#1b4b3d",
           primaryColorSuppl: "#245f4e",
           infoColor: "#356d86",
           successColor: "#2e7d5b",
           warningColor: "#b7791f",
           errorColor: "#b4443f",
           bodyColor: "#111714",
           baseColor: "#1d2823",
           cardColor: "#1d2823",
           modalColor: "#1d2823",
           popoverColor: "#1d2823",
           borderColor: "rgba(213, 219, 213, 0.2)",
           dividerColor: "rgba(213, 219, 213, 0.16)",
           textColorBase: "#f7f8f6",
           textColor1: "#f7f8f6",
           textColor2: "rgba(247, 248, 246, 0.84)",
           textColor3: "rgba(213, 219, 213, 0.72)",
           borderRadius: "10px",
           borderRadiusSmall: "6px",
         },
         Tabs: {
            tabTextColorLine: "rgba(247, 248, 246, 0.82)",
            tabTextColorActiveLine: "#8fd9bb",
            tabTextColorHoverLine: "#b7ead8",
            tabTextColorDisabledLine: "rgba(213, 219, 213, 0.5)",
            barColor: "#8fd9bb",
            tabFontWeight: "450",
            tabFontWeightActive: "500",
         },
         Button: {
            textColorPrimary: "#f7f8f6",
            textColorHoverPrimary: "#f7f8f6",
            textColorPressedPrimary: "#f7f8f6",
            textColorFocusPrimary: "#f7f8f6",
            fontWeightStrong: "500",
         },
     },
      // Dark is an OVERRIDE set. getEffectiveCss folds it over light.
      css: {
         "--mw-color-primary": "#245f4e",
         "--mw-color-primary-strong": "#1b4b3d",
         "--mw-color-primary-soft": "rgba(36, 95, 78, 0.18)",
         "--mw-color-surface-base": "#111714",
         "--mw-color-surface-raised": "#17201c",
         "--mw-color-surface-panel": "#1d2823",
         "--mw-color-border": "rgba(213, 219, 213, 0.2)",
         "--mw-color-border-strong": "rgba(213, 219, 213, 0.28)",
         "--mw-color-text-primary": "#f7f8f6",
         "--mw-color-text-secondary": "rgba(247, 248, 246, 0.84)",
         "--mw-color-text-muted": "rgba(213, 219, 213, 0.72)",
         "--mw-surface-card": "rgba(29, 40, 35, 0.94)",
         "--mw-surface-card-muted": "rgba(23, 32, 28, 0.92)",
         "--mw-surface-card-subtle": "rgba(17, 23, 20, 0.78)",
         "--mw-surface-card-success": "rgba(36, 95, 78, 0.22)",
         "--mw-surface-card-warning": "rgba(183, 121, 31, 0.16)",
         "--mw-surface-header": "rgba(24, 33, 29, 0.92)",
         "--mw-surface-shell": "rgba(24, 33, 29, 0.9)",
         "--mw-surface-mission": "rgba(36, 95, 78, 0.22)",
         "--mw-surface-active": "color-mix(in srgb, var(--mw-color-primary) 30%, transparent)",
         "--mw-control-readonly-border": "var(--mw-color-border-strong)",
         "--mw-control-readonly-bg": "color-mix(in srgb, var(--mw-color-primary) 34%, transparent)",
         "--mw-control-readonly-text": "var(--mw-color-text-primary)",
         "--mw-shadow-soft": "0 12px 28px rgba(0, 0, 0, 0.28)",
         "--mw-shadow-card": "0 10px 24px rgba(0, 0, 0, 0.22)",
         "--color-background": "var(--mw-color-surface-base)",
         "--color-background-soft": "var(--mw-color-surface-raised)",
         "--color-background-mute": "var(--mw-color-surface-panel)",
         "--color-border": "rgba(213, 219, 213, 0.16)",
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