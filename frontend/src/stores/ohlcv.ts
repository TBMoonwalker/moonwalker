import { defineStore } from 'pinia'

export const useOhlcvStore = defineStore('ohlcv', {
  state: () => ({
    cache: new Map<string, any>()
  }),
  actions: {
    get(key: string) {
      return this.cache.get(key)
    },
    set(key: string, value: any) {
      this.cache.set(key, value)
    }
  }
})
