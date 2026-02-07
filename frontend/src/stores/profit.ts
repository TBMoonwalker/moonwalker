import { ref } from 'vue'
import { defineStore } from 'pinia'
import { fetchJson } from '../api/client'

export const useProfitDatastore = defineStore('profit', () => {
    const data = ref()
    async function load_profit_history_data(period: string) {
        const timestamp: number = Math.floor(Date.now() / 1000)
        data.value = await fetchJson(
            `/statistic/profit/${timestamp}/${period}`
        )
    }

    return { data, load_profit_history_data }

})
