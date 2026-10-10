import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { readJSON, readText, removeJSON, writeJSON, writeText } from "../src/helpers/safeStorage";

describe("safeStorage", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("preserves literal preference formats", () => {
    for (const value of ["dark", "full", "true"]) {
      writeText("preference", value);
      expect(localStorage.getItem("preference")).toBe(value);
      expect(readText("preference")).toBe(value);
    }
  });

  it("uses the injected storage without falling back to browser storage", () => {
    localStorage.setItem("k", "browser");
    const entries = new Map<string, string>();
    const storage = () => ({
      getItem: (key: string) => entries.get(key) ?? null,
      setItem: (key: string, value: string) => { entries.set(key, value); },
      removeItem: (key: string) => { entries.delete(key); },
    });
    writeText("k", "injected", storage);
    expect(readText("k", storage)).toBe("injected");
    removeJSON("k", storage);
    expect(readText("k", storage)).toBeNull();
    expect(readText("k", () => null)).toBeNull();
    expect(localStorage.getItem("k")).toBe("browser");
  });

  it("catches a throwing browser storage getter for text and JSON operations", () => {
    vi.spyOn(window, "localStorage", "get").mockImplementation(() => {
      throw new Error("storage blocked");
    });
    expect(readText("k")).toBeNull();
    expect(readJSON("k")).toBeNull();
    expect(() => writeText("k", "dark")).not.toThrow();
    expect(() => writeJSON("k", { a: 1 })).not.toThrow();
    expect(() => removeJSON("k")).not.toThrow();
  });

  it.each(["getItem", "setItem", "removeItem"] as const)("tolerates blocked %s", (blocked) => {
    const storage = () => ({
      getItem: vi.fn(() => "dark"),
      setItem: vi.fn(),
      removeItem: vi.fn(),
      [blocked]: () => { throw new Error("blocked"); },
    });
    expect(() => readText("k", storage)).not.toThrow();
    expect(() => writeText("k", "dark", storage)).not.toThrow();
    expect(() => removeJSON("k", storage)).not.toThrow();
  });

  it("keeps the prior JSON value when serialization fails", () => {
    writeJSON("k", { a: 1 });
    const cyclic: { self?: unknown } = {};
    cyclic.self = cyclic;
    expect(() => writeJSON("k", cyclic)).not.toThrow();
    expect(readJSON("k")).toEqual({ a: 1 });
  });

  it("round-trips a JSON value", () => {
    writeJSON("k", { a: 1, b: "x" });
    expect(readJSON<{ a: number; b: string }>("k")).toEqual({ a: 1, b: "x" });
  });

  it("returns null for a missing key", () => {
    expect(readJSON("missing")).toBeNull();
  });

  it("degrades a corrupt entry to null", () => {
    localStorage.setItem("k", "{not json");
    expect(readJSON("k")).toBeNull();
  });

  it("removes a stored key", () => {
    writeJSON("k", { a: 1 });
    removeJSON("k");
    expect(readJSON("k")).toBeNull();
  });

  it("writeJSON degrades to a no-op when storage throws", () => {
    vi.spyOn(localStorage, "setItem").mockImplementation(() => {
      throw new Error("quota exceeded");
    });
    expect(() => writeJSON("k", { a: 1 })).not.toThrow();
  });

  it("readJSON degrades to null when storage throws", () => {
    vi.spyOn(localStorage, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(readJSON("k")).toBeNull();
  });

  it("does not read or write on a corrupt setItem without throwing", () => {
    localStorage.setItem("k", JSON.stringify({ a: 1 }));
    vi.spyOn(localStorage, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    // A blocked write leaves the prior value intact and never throws.
    expect(() => writeJSON("k", { a: 2 })).not.toThrow();
  });
});
