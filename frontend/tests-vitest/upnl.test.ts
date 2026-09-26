import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";

const fetchJsonMock = vi.hoisted(() => vi.fn());

vi.mock("../src/api/client", () => ({
  fetchJson: fetchJsonMock,
}));

import { useUpnlDatastore } from "../src/stores/upnl";

const STORAGE_KEY = "mw_upnl_overall_timeline";

const CACHED_POINTS = [
  { timestamp: "2026-01-01 00:00:00", profit_overall: 1, funds_locked: 100 },
  { timestamp: "2026-01-02 00:00:00", profit_overall: 2, funds_locked: 110 },
];

function seedStorage(points: unknown, storedAt = Date.now()): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify({ points, storedAt }));
}

describe("useUpnlDatastore · web-storage stale-while-revalidate", () => {
  beforeEach(() => {
    localStorage.clear();
    fetchJsonMock.mockReset();
    // A fresh Pinia re-instantiates the setup store so the cache seed reads storage
    // on every `useUpnlDatastore()` call.
    setActivePinia(createPinia());
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  function store(): ReturnType<typeof useUpnlDatastore> {
    return useUpnlDatastore();
  }

  it("seeds `data` from a warm cache without a network call", () => {
    seedStorage(CACHED_POINTS);
    const s = store();
    expect(s.data).toEqual(CACHED_POINTS);
    expect(fetchJsonMock).not.toHaveBeenCalled();
  });

  it("starts empty on a cold cache", () => {
    const s = store();
    expect(s.data).toEqual([]);
  });

  it("persists a fetched timeline to storage on success", async () => {
    const fresh = [
      { timestamp: "2026-01-03 00:00:00", profit_overall: 3, funds_locked: 120 },
    ];
    fetchJsonMock.mockResolvedValueOnce(fresh);

    const s = store();
    await s.load_upnl_history_data();

    expect(s.data).toEqual(fresh);
    const written = JSON.parse(localStorage.getItem(STORAGE_KEY) as string);
    expect(written.points).toEqual(fresh);
    expect(typeof written.storedAt).toBe("number");
  });

  it("paints the warm cache, then reconciles with fresh server data", async () => {
    seedStorage(CACHED_POINTS);
    const fresh = [
      ...CACHED_POINTS,
      { timestamp: "2026-01-03 00:00:00", profit_overall: 9, funds_locked: 900 },
    ];
    fetchJsonMock.mockResolvedValueOnce(fresh);

    const s = store();
    expect(s.data).toEqual(CACHED_POINTS); // instant paint from cache

    await s.load_upnl_history_data();
    expect(s.data).toEqual(fresh); // reconciled in the background
    expect(JSON.parse(localStorage.getItem(STORAGE_KEY) as string).points).toEqual(
      fresh,
    );
  });

  it("does not persist or throw when a blocked write is the only failure", async () => {
    vi.spyOn(localStorage, "setItem").mockImplementation(() => {
      throw new Error("quota exceeded");
    });
    const fresh = [
      { timestamp: "2026-01-01 00:00:00", profit_overall: 1, funds_locked: 1 },
    ];
    fetchJsonMock.mockResolvedValueOnce(fresh);

    const s = store(); // cold cache -> empty seed, read path is fine
    await expect(s.load_upnl_history_data()).resolves.toEqual(fresh);
    expect(s.data).toEqual(fresh);
  });

  it("keeps cached `data` on a failed revalidate (no clobber)", async () => {
    seedStorage(CACHED_POINTS);
    fetchJsonMock.mockRejectedValueOnce(new Error("network down"));

    const s = store();
    expect(s.data).toEqual(CACHED_POINTS);
    await expect(s.load_upnl_history_data()).rejects.toThrow("network down");
    // `data` was seeded and never reassigned, so the cached view survives.
    expect(s.data).toEqual(CACHED_POINTS);
  });
});
