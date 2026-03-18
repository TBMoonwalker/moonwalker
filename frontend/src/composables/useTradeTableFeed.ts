import { computed, ref, watch, type Ref } from 'vue'
import { storeToRefs } from 'pinia'

import { useWebSocketDataStore } from '../stores/websocket'

type NormalizeRows<T> = (rawRows: unknown[]) => T[]

type UseTradeTableFeedOptions<T> = {
  websocketId: string
  waitingText: string
  emptyText: string
  normalizeRows: NormalizeRows<T>
}

type UseTradeTableFeedResult<T> = {
  rows: Ref<T[]>
  hasReceivedData: Ref<boolean>
  status: Ref<string>
  isTableLoading: Ref<boolean>
  tableEmptyText: Ref<string>
}

export function useTradeTableFeed<T>(
  options: UseTradeTableFeedOptions<T>,
): UseTradeTableFeedResult<T> {
  const { websocketId, waitingText, emptyText, normalizeRows } = options
  const websocketStore = useWebSocketDataStore(websocketId)
  const websocketState = storeToRefs(websocketStore)
  const rows = ref<T[]>([])

  watch(
    websocketState.data,
    (nextData) => {
      if (!Array.isArray(nextData)) {
        rows.value = []
        return
      }
      rows.value = normalizeRows(nextData as unknown[])
    },
    { immediate: true },
  )

  const isTableLoading = computed(
    () =>
      !websocketState.hasReceivedData.value &&
      websocketState.status.value !== 'CLOSED',
  )
  const tableEmptyText = computed(() =>
    websocketState.hasReceivedData.value ? emptyText : waitingText,
  )

  return {
    rows,
    hasReceivedData: websocketState.hasReceivedData,
    status: websocketState.status,
    isTableLoading,
    tableEmptyText,
  }
}
