/**
 * Theme store — the single owner of the user's `auto | light | dark` color-scheme
 * choice and the resolved scheme the rest of the app consumes: Naive UI's
 * `themeOverrides` in App.vue and the `data-mw-theme` attribute the CSS override
 * blocks in assets/base.css read.
 *
 * "auto" follows the OS `prefers-color-scheme` signal via `useOsTheme`; an
 * explicit "light" / "dark" forces a scheme regardless of the OS. The choice is
 * persisted to localStorage and mirrored onto `<html>` so a forced selection can
 * retheme the CSS layer the `@media` query alone cannot. A pre-paint script in
 * index.html reads the same key before first paint (see themeMode.ts) to avoid a
 * flash; this store re-applies the stored choice on mount as a post-hydration
 * safety net.
 */

import { computed, ref } from "vue"
import { defineStore } from "pinia"
import { useOsTheme } from "vooks"

import {
  THEME_STORAGE_KEY,
  modeToAttribute,
  parseStoredMode,
  resolveScheme,
  type ThemeMode,
} from "./themeMode"

// Re-export so consumers can import the mode type alongside the store.
export type { ThemeMode } from "./themeMode"

/**
 * Mirror the current mode onto `<html data-mw-theme>`. "auto" clears the
 * attribute so the CSS `@media (prefers-color-scheme)` query decides; a forced
 * choice sets it so the matching override block in base.css wins.
 */
function applyAttribute(mode: ThemeMode): void {
  const attribute = modeToAttribute(mode)
  const element = document.documentElement
  if (attribute === null) {
    element.removeAttribute("data-mw-theme")
   } else {
    element.setAttribute("data-mw-theme", attribute)
   }
}

/** Read the persisted choice, tolerating a missing or blocked localStorage. */
function readInitialMode(): ThemeMode {
  try {
    return parseStoredMode(localStorage.getItem(THEME_STORAGE_KEY))
   } catch {
    return "auto"
   }
}

/**
 * Persist the choice to localStorage. Storage may be blocked (private mode or a
 * locked-down profile); the attribute is still applied for this session, so a
 * failed write degrades gracefully rather than throwing.
 */
function persist(mode: ThemeMode): void {
  try {
    localStorage.setItem(THEME_STORAGE_KEY, mode)
   } catch {
     // No-op: the choice is still applied via applyAttribute() for this session.
   }
}

export const useThemeStore = defineStore("theme", () => {
  const osScheme = useOsTheme()

  // The user's persisted choice; "auto" until they choose "light" / "dark".
  const mode = ref<ThemeMode>(readInitialMode())

  // The concrete scheme the Naive UI override and the CSS cascade consume.
  const scheme = computed(() => resolveScheme(mode.value, osScheme.value))

  // Re-apply the restored choice on mount: the pre-paint script already set the
  // attribute, but a reload can clear it without clearing storage, so re-mirror.
  applyAttribute(mode.value)

  function setMode(next: ThemeMode): void {
    mode.value = next
    persist(next)
    applyAttribute(next)
   }

  return { mode, scheme, setMode }
})
