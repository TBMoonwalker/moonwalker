import { ref } from 'vue'
import { defineStore } from 'pinia'
import { fetchJson } from '../api/client'

type ProfitHistory = Record<string, number>

const PROFIT_HISTORY_CACHE_TTL_MS = 5 * 60 * 1000

export const useProfitDatastore = defineStore('profit', () => {
    const data = ref<ProfitHistory>({})
    const dataByPeriod = ref<Record<string, ProfitHistory>>({})
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
