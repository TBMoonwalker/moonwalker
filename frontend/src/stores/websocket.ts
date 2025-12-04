import { ref } from 'vue'
import { defineStore } from 'pinia'

export const useWebSocketDataStore = (wsId: string) => defineStore(`${wsId}`, {
  state: () => {
    return {
      json: ref()
    }
  }
})()