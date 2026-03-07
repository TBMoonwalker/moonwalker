import { defineStore } from 'pinia'

export const useWebSocketDataStore = (wsId: string) => defineStore(`${wsId}`, {
  state: () => {
    return {
      raw: null as string | null,
      data: null as unknown
    }
  },
  actions: {
    setRaw(payload: string | null) {
      this.raw = payload
      if (payload === null || payload === undefined) {
        this.data = null
        return
      }
      try {
        this.data = JSON.parse(payload)
      } catch {
        this.data = null
      }
    }
  }
})()
