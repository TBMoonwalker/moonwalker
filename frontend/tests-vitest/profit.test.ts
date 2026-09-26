import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";

const fetchJsonMock = vi.hoisted(() => vi.fn());

vi.mock("../src/api/client", () => ({
    fetchJson: fetchJsonMock,
}));

import { useProfitDatastore } from "../src/stores/profit";

const STORAGE_KEY = "mw_profit_history";

const DAILY = { "2026-01-01": 10, "2026-01-02": 20 };
const MONTHLY = { "2026-01": 30, "2026-02": 40 };

function seedStorage(byPeriod: Record<string, Record<string, number>>): void {
    localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({ byPeriod, storedAt: Date.now() }),
     );
}

describe("useProfitDatastore · web-storage stale-while-revalidate", () => {
    beforeEach(() => {
        localStorage.clear();
        fetchJsonMock.mockReset();
         // A fresh Pinia re-instantiates the setup store so the cache seed reads
         // storage on every `useProfitDatastore()` call.
        setActivePinia(createPinia());
     });

    afterEach(() => {
        vi.restoreAllMocks();
     });

    function store(): ReturnType<typeof useProfitDatastore> {
        return useProfitDatastore();
     }

    it("seeds each period from a warm cache without a network call", () => {
        seedStorage({ daily: DAILY, monthly: MONTHLY });
        const s = store();
        expect(s.get_profit_history_data("daily")).toEqual(DAILY);
        expect(s.get_profit_history_data("monthly")).toEqual(MONTHLY);
        expect(fetchJsonMock).not.toHaveBeenCalled();
     });

    it("starts empty on a cold cache", () => {
        const s = store();
        expect(s.get_profit_history_data("daily")).toEqual({});
     });

    it("persists a fetched period to storage on success", async () => {
        const fresh = { "2026-01-03": 30 };
        fetchJsonMock.mockResolvedValueOnce(fresh);

        const s = store();
        await s.load_profit_history_data("daily");

        expect(s.get_profit_history_data("daily")).toEqual(fresh);
        const written = JSON.parse(localStorage.getItem(STORAGE_KEY) as string);
        expect(written.byPeriod.daily).toEqual(fresh);
        expect(typeof written.storedAt).toBe("number");
     });

    it("paints the warm cache, then reconciles with fresh server data", async () => {
        seedStorage({ daily: DAILY });
        const fresh = { "2026-01-01": 10, "2026-01-03": 900 };
        fetchJsonMock.mockResolvedValueOnce(fresh);

        const s = store();
        expect(s.get_profit_history_data("daily")).toEqual(DAILY);

        await s.load_profit_history_data("daily");
        expect(s.get_profit_history_data("daily")).toEqual(fresh);
        expect(
            JSON.parse(localStorage.getItem(STORAGE_KEY) as string).byPeriod.daily,
         ).toEqual(fresh);
     });

    it("merges periods so a later load does not evict an earlier one", async () => {
        seedStorage({ daily: DAILY });
        fetchJsonMock.mockResolvedValueOnce(MONTHLY);

        const s = store();
        expect(s.get_profit_history_data("daily")).toEqual(DAILY);
        await s.load_profit_history_data("monthly");
        expect(s.get_profit_history_data("monthly")).toEqual(MONTHLY);
         // 'daily' survives the 'monthly' load and the whole-store persist.
        expect(s.get_profit_history_data("daily")).toEqual(DAILY);
        const written = JSON.parse(localStorage.getItem(STORAGE_KEY) as string);
        expect(written.byPeriod.daily).toEqual(DAILY);
        expect(written.byPeriod.monthly).toEqual(MONTHLY);
     });

    it("serves a second load within the TTL from the in-memory cache", async () => {
        const fresh = { "2026-01-03": 30 };
        fetchJsonMock.mockResolvedValueOnce(fresh);

        const s = store();
        await s.load_profit_history_data("daily");
        expect(fetchJsonMock).toHaveBeenCalledTimes(1);

         // A second, non-forced load inside the 5-minute TTL reuses the cache.
        await s.load_profit_history_data("daily");
        expect(fetchJsonMock).toHaveBeenCalledTimes(1);
        expect(s.get_profit_history_data("daily")).toEqual(fresh);
     });

    it("keeps cached periods and does not throw on a blocked write", async () => {
        seedStorage({ daily: DAILY });
        vi.spyOn(localStorage, "setItem").mockImplementation(() => {
            throw new Error("quota exceeded");
             });
        const fresh = { "2026-01-03": 30 };
        fetchJsonMock.mockResolvedValueOnce(fresh);

        const s = store();
        await expect(s.load_profit_history_data("daily")).resolves.toEqual(fresh);
        expect(s.get_profit_history_data("daily")).toEqual(fresh);
     });
});
