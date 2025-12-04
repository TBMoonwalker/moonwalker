import { ref } from 'vue'
import { defineStore } from 'pinia'
import { MOONWALKER_API_PORT, MOONWALKER_API_HOST } from '../config'

export const useProfitDatastore = defineStore('profit', () => {
    const data = ref()
    async function load_profit_history_data(period: string) {
        const timestamp: number = Math.floor(Date.now() / 1000)
        data.value = await fetch(`http://${MOONWALKER_API_HOST}:${MOONWALKER_API_PORT}/statistic/profit/${timestamp}/${period}`).then((response) =>
            response.json()
        )
    }

    return { data, load_profit_history_data }

})