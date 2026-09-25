import { describe, expect, it } from "vitest"

import {
  THEME_STORAGE_KEY,
  modeToAttribute,
  parseStoredMode,
  resolveScheme,
} from "../src/theme/themeMode"

describe("themeMode · resolveScheme", () => {
  it("delegates to the OS when the user chose auto", () => {
    expect(resolveScheme("auto", "light")).toBe("light")
    expect(resolveScheme("auto", "dark")).toBe("dark")
  })

  it("forces light regardless of the current OS scheme", () => {
    expect(resolveScheme("light", "light")).toBe("light")
    expect(resolveScheme("light", "dark")).toBe("light")
  })

  it("forces dark regardless of the current OS scheme", () => {
    expect(resolveScheme("dark", "light")).toBe("dark")
    expect(resolveScheme("dark", "dark")).toBe("dark")
  })
})

describe("themeMode · modeToAttribute", () => {
  it("leaves auto unset so the @media query can decide", () => {
    expect(modeToAttribute("auto")).toBeNull()
  })

  it("maps an explicit choice to its attribute value", () => {
    expect(modeToAttribute("light")).toBe("light")
    expect(modeToAttribute("dark")).toBe("dark")
  })
})

describe("themeMode · parseStoredMode", () => {
  it("accepts only the literal light / dark as forced modes", () => {
    expect(parseStoredMode("light")).toBe("light")
    expect(parseStoredMode("dark")).toBe("dark")
  })

  it("falls back to auto for any other, stale, or tampered value", () => {
    expect(parseStoredMode("auto")).toBe("auto")
    expect(parseStoredMode(null)).toBe("auto")
    expect(parseStoredMode(undefined)).toBe("auto")
    expect(parseStoredMode("")).toBe("auto")
    expect(parseStoredMode("LIGHT")).toBe("auto")
    expect(parseStoredMode("bogus")).toBe("auto")
  })
})

describe("themeMode · THEME_STORAGE_KEY", () => {
  it("is the single key the FOUC script and the store share", () => {
    expect(THEME_STORAGE_KEY).toBe("mw-theme-mode")
  })
})
