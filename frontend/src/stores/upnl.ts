import { ref } from 'vue'
import { defineStore } from 'pinia'
import { fetchJson } from '../api/client'

type UpnlPoint = {
  timestamp: string
  profit_overall: number
}

export const useUpnlDatastore = defineStore('upnl', () => {
  const data = ref<UpnlPoint[]>([])

  async function load_upnl_history_data() {
    data.value = await fetchJson<UpnlPoint[]>('/statistic/upnl/all')
  }

  return { data, load_upnl_history_data }
})
