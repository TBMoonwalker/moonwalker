import { defineStore } from 'pinia'

export type WebSocketStatus = 'CONNECTING' | 'OPEN' | 'CLOSED'

export const useWebSocketDataStore = (wsId: string) => defineStore(`${wsId}`, {
  state: () => {
    return {
      raw: null as string | null,
      data: null as unknown,
      status: 'CONNECTING' as WebSocketStatus,
      hasReceivedData: false,
      lastMessageAt: null as number | null,
      lastStatusAt: null as number | null,
      reconnectCount: 0,
    }
  },
  actions: {
    setRaw(payload: string | null) {
      this.raw = payload
      this.hasReceivedData = true
      this.lastMessageAt = Date.now()
      if (payload === null || payload === undefined) {
        this.data = null
        return
      }
      try {
        this.data = JSON.parse(payload)
      } catch {
        this.data = null
      }
    },
    setStatus(status: WebSocketStatus) {
      this.status = status
      this.lastStatusAt = Date.now()
    },
    markReconnect() {
      this.reconnectCount += 1
      this.lastStatusAt = Date.now()
    }
  }
})()
