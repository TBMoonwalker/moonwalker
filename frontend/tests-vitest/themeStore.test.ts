import {
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
} from "vitest"
import { createPinia, setActivePinia } from "pinia"

import { useThemeStore } from "../src/theme/themeStore"

// jsdom does not implement `window.matchMedia`, which the store's `useOsTheme()`
// reads at creation time, so install a minimal stub before any store is created.
// Forced choices are OS-independent, so the stubbed `matches: false` (light) value
// is irrelevant to these assertions; the auto-follows-OS branch and the localStorage
// load/validate logic live in themeMode.test.ts.
function installMatchMediaStub(): void {
  const stub = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    addListener: () => undefined,
    removeListener: () => undefined,
    dispatchEvent: () => false,
   })) as unknown as (query: string) => MediaQueryList
  window.matchMedia = stub
 }

beforeAll(() => {
  installMatchMediaStub()
 })

beforeEach(() => {
  document.documentElement.removeAttribute("data-mw-theme")
   // A fresh Pinia re-instantiates the setup store so `useOsTheme()` re-queries the
   // OS and `readInitialMode()` re-initialises `mode` on each mount.
  setActivePinia(createPinia())
 })

describe("themeStore · forced choices", () => {
  it("forces dark regardless of the OS and mirrors the attribute", () => {
    const store = useThemeStore()
    store.setMode("dark")
    expect(store.mode).toBe("dark")
    expect(store.scheme).toBe("dark")
    expect(document.documentElement.getAttribute("data-mw-theme")).toBe("dark")
  })

  it("forces light and mirrors the attribute", () => {
    const store = useThemeStore()
    store.setMode("light")
    expect(store.mode).toBe("light")
    expect(store.scheme).toBe("light")
    expect(document.documentElement.getAttribute("data-mw-theme")).toBe("light")
  })

  it("switching back to auto clears the forced attribute", () => {
    const store = useThemeStore()
    store.setMode("dark")
    expect(document.documentElement.getAttribute("data-mw-theme")).toBe("dark")
    store.setMode("auto")
    expect(store.mode).toBe("auto")
    expect(document.documentElement.getAttribute("data-mw-theme")).toBeNull()
  })
 })

describe("themeStore · init", () => {
  it("leaves the attribute absent for auto with no stored choice", () => {
    const store = useThemeStore()
    expect(store.mode).toBe("auto")
    expect(document.documentElement.getAttribute("data-mw-theme")).toBeNull()
  })
 })
