import { ref } from 'vue'
import { defineStore } from 'pinia'
import { fetchJson } from '../api/client'
import { readJSON, writeJSON } from '../helpers/safeStorage'

type UpnlPoint = {
  timestamp: string
  profit_overall: number
  funds_locked: number
}

const UPNL_HISTORY_CACHE_TTL_MS = 5 * 60 * 1000

/**
 * Persisted overall/uPNL timeline payload.
 *
 * A full page reload wipes the in-memory Pinia store, which today forces a
 * blocking re-fetch and full re-ship of the whole "overall" series on every
 * reopen. Storing the last good payload lets the chart paint instantly from a
 * warm cache, then a background revalidate reconciles with the freshest server
 * data (stale-while-revalidate). See docs/designs/delta-loading.md, P0.
 */
const UPNL_TIMELINE_STORAGE_KEY = 'mw_upnl_overall_timeline'
interface StoredUpnlTimeline {
  points: UpnlPoint[]
  storedAt: number
}

export const useUpnlDatastore = defineStore('upnl', () => {
  // Seed from a warm web-storage cache for an instant first paint after a reload.
  // A missing, blocked, or corrupt entry leaves `data` empty (same as a cold start).
  const storedTimeline = readJSON<StoredUpnlTimeline>(UPNL_TIMELINE_STORAGE_KEY)
  const data = ref<UpnlPoint[]>(
   storedTimeline && Array.isArray(storedTimeline.points)
     ? storedTimeline.points
     : []
  )
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
     // Persist the authoritative snapshot so the next reload paints from cache.
     writeJSON(UPNL_TIMELINE_STORAGE_KEY, {
        points: payload,
        storedAt: Date.now(),
      })
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
