import { ref } from 'vue'
import { defineStore } from 'pinia'
import { fetchJson } from '../api/client'

type UpnlPoint = {
  timestamp: string
  profit_overall: number
  funds_locked: number
}

const UPNL_HISTORY_CACHE_TTL_MS = 5 * 60 * 1000

export const useUpnlDatastore = defineStore('upnl', () => {
  const data = ref<UpnlPoint[]>([])
  const loadedAt = ref<number | null>(null)
  const isLoading = ref(false)
  let pendingLoad: Promise<UpnlPoint[]> | null = null

  function hasFreshCache(): boolean {
    return (
      loadedAt.value !== null &&
      Date.now() - loadedAt.value < UPNL_HISTORY_CACHE_TTL_MS
    )
  }

  async function load_upnl_history_data(options: { force?: boolean } = {}) {
    if (!options.force && hasFreshCache()) {
      return data.value
    }
    if (pendingLoad) {
      return pendingLoad
    }

    isLoading.value = true
    pendingLoad = fetchJson<UpnlPoint[]>('/statistic/profit-overall/timeline')
      .then((payload) => {
        data.value = payload
        loadedAt.value = Date.now()
        return payload
      })
      .finally(() => {
        isLoading.value = false
        pendingLoad = null
      })

    return pendingLoad
  }

  return { data, loadedAt, isLoading, load_upnl_history_data }
})
