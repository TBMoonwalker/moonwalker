import { ref } from 'vue'
import { defineStore } from 'pinia'
import { fetchJson } from '../api/client'
import { readJSON, writeJSON } from '../helpers/safeStorage'

type ProfitHistory = Record<string, number>

const PROFIT_HISTORY_CACHE_TTL_MS = 5 * 60 * 1000

// Persist the per-period profit history (daily/monthly/yearly) to web storage so a
// full page reload (which wipes the in-memory Pinia store) paints each tab instantly
// from a warm cache, then a background revalidate reconciles (stale-while-revalidate,
// mirroring stores/upnl.ts). See docs/designs/delta-loading.md, P0.
const PROFIT_HISTORY_STORAGE_KEY = 'mw_profit_history'

interface StoredProfitByPeriod {
    byPeriod: Record<string, ProfitHistory>
    storedAt: number
}

export const useProfitDatastore = defineStore('profit', () => {
    // Seed from a warm web-storage cache so a page reload paints each profit tab
    // instantly (stale-while-revalidate). A missing, blocked, or corrupt entry is a
    // no-op; a subsequent load reconciles and re-persists.
    const storedProfit = readJSON<StoredProfitByPeriod>(
        PROFIT_HISTORY_STORAGE_KEY,
      )
    const data = ref<ProfitHistory>({})
    const dataByPeriod = ref<Record<string, ProfitHistory>>(
        storedProfit && storedProfit.byPeriod ? { ...storedProfit.byPeriod } : {},
      )
    const loadedAtByPeriod = ref<Record<string, number>>({})
    const isLoadingByPeriod = ref<Record<string, boolean>>({})
    const pendingLoads: Record<string, Promise<ProfitHistory> | undefined> = {}

    function hasFreshCache(period: string): boolean {
        const loadedAt = loadedAtByPeriod.value[period]
        return (
            loadedAt !== undefined &&
            Date.now() - loadedAt < PROFIT_HISTORY_CACHE_TTL_MS
         )
     }

    async function load_profit_history_data(
        period: string,
        options: { force?: boolean } = {},
         ) {
        if (!options.force && hasFreshCache(period)) {
            data.value = dataByPeriod.value[period] ?? {}
            return data.value
         }
        if (pendingLoads[period]) {
            data.value = await pendingLoads[period]
            return data.value
          }

        const timestamp: number = Math.floor(Date.now() / 1000)
        isLoadingByPeriod.value = {
             ...isLoadingByPeriod.value,
             [period]: true,
            }
        pendingLoads[period] = fetchJson<ProfitHistory>(
             `/statistic/profit/${timestamp}/${period}`
            )
                .then((payload) => {
                    dataByPeriod.value = {
                         ...dataByPeriod.value,
                         [period]: payload,
                        }
                     loadedAtByPeriod.value = {
                         ...loadedAtByPeriod.value,
                         [period]: Date.now(),
                        }
                     data.value = payload
                      // Persist the per-period cache so a page reload paints each tab
                      // instantly. The revalidate stays in the background.
                     writeJSON(PROFIT_HISTORY_STORAGE_KEY, {
                         byPeriod: dataByPeriod.value,
                         storedAt: Date.now(),
                        })
                     return payload
                    })
                .finally(() => {
                    isLoadingByPeriod.value = {
                         ...isLoadingByPeriod.value,
                         [period]: false,
                        }
                     pendingLoads[period] = undefined
                    })

        data.value = await pendingLoads[period]
        return data.value
         }

    function get_profit_history_data(period: string): ProfitHistory {
        return dataByPeriod.value[period] ?? {}
         }

    return {
        data,
        dataByPeriod,
        loadedAtByPeriod,
        isLoadingByPeriod,
        get_profit_history_data,
        load_profit_history_data,
        }

})
