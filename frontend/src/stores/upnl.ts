import { ref } from 'vue'
import { defineStore } from 'pinia'
import { fetchJson } from '../api/client'

type UpnlPoint = {
  timestamp: string
  profit_overall: number
  funds_locked: number
}

export const useUpnlDatastore = defineStore('upnl', () => {
  const data = ref<UpnlPoint[]>([])

  async function load_upnl_history_data() {
    data.value = await fetchJson<UpnlPoint[]>('/statistic/profit-overall/timeline')
  }

  return { data, load_upnl_history_data }
})
