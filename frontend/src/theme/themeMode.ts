/**
 * Theme mode — the pure, framework-agnostic decision logic for Moonwalker's
 * user-selectable `auto | light | dark` color scheme (T1 Phase 3).
 *
 * "auto" delegates to the OS `prefers-color-scheme` signal; "light" / "dark"
 * force a scheme regardless of the OS. This module is deliberately DOM-free so the
 * exact resolution the FOUC guard and the Pinia store apply can be unit-tested
 * with no browser. `THEME_STORAGE_KEY` is the one key the pre-paint script
 * (index.html) and the store (themeStore.ts) both read and write, so a forced
 * choice survives a reload with no flash of the wrong theme.
 */

import type { ColorScheme } from "./tokens"

/** A user's color-scheme choice. */
export type ThemeMode = "auto" | "light" | "dark"

/**
 * localStorage key holding the user's forced choice. Read by the pre-paint FOUC
 * script in index.html and written by the store; both import this constant so the
 * two can never drift to a different key.
 */
export const THEME_STORAGE_KEY = "mw-theme-mode"

/**
 * Resolve a user choice against the current OS scheme to a concrete color scheme.
 * "auto" follows the OS; an explicit choice wins regardless of the OS.
 */
export function resolveScheme(
  mode: ThemeMode,
  os: ColorScheme,
): ColorScheme {
  return mode === "auto" ? os : mode
}

/**
 * The `data-mw-theme` attribute the FOUC script and the store place on
 * `document.documentElement`. "auto" returns `null` (leave the attribute absent)
 * so the CSS `@media (prefers-color-scheme: dark)` query decides — the forced
 * blocks in base.css only fire for an explicit value, so absent-means-auto keeps
 * the default (auto) path visually untouched.
 */
export function modeToAttribute(mode: ThemeMode): string | null {
  return mode === "auto" ? null : mode
}

/**
 * Parse a stored value into a valid mode. Anything that is not an explicit
 * "light" / "dark" — a stale, empty, or tampered key — falls back to "auto", so
 * a bad stored value can never leave the UI in a broken (un-themable) state.
 */
export function parseStoredMode(
  raw: string | null | undefined,
): ThemeMode {
  return raw === "light" || raw === "dark" ? raw : "auto"
}
