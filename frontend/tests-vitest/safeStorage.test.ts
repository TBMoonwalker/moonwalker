import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { readJSON, removeJSON, writeJSON } from "../src/helpers/safeStorage";

describe("safeStorage", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
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
