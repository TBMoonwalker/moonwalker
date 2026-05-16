import { onMounted, reactive, ref, watch, type Ref } from 'vue'

import { fetchJson } from '../api/client'
import type { TradeTableSortState } from '../helpers/tradeTable'

type NormalizeRows<T> = (rawRows: unknown[]) => T[]

type UsePagedTradeFeedOptions<T> = {
  liveRows: Ref<T[]>
  normalizeRows: NormalizeRows<T>
  lengthEndpoint: string
  pageEndpoint: (
    offset: number,
    sortState: TradeTableSortState | null,
  ) => string
  itemLabel: string
  pageSize?: number
  lengthRefreshIntervalMs?: number
  sortState?: Ref<TradeTableSortState | null>
  shouldUseLiveRows?: (sortState: TradeTableSortState | null) => boolean
}

type PaginationState = {
  page: number
  pageCount: number
  pageSize: number
  pageSlot: number
  itemCount?: number
  prefix: (info: { itemCount: number }) => string
}

type UsePagedTradeFeedResult<T> = {
  pagedRows: Ref<T[]>
  pagination: PaginationState
  handlePageChange: (currentPage: number) => Promise<void>
  refreshLength: (force?: boolean) => Promise<void>
  refreshPageAfterDelete: () => Promise<void>
}

export function usePagedTradeFeed<T>(
  options: UsePagedTradeFeedOptions<T>,
): UsePagedTradeFeedResult<T> {
  const {
    liveRows,
    normalizeRows,
    lengthEndpoint,
    pageEndpoint,
    itemLabel,
    pageSize = 10,
    lengthRefreshIntervalMs = 5000,
    sortState,
    shouldUseLiveRows,
  } = options

  const totalCount = ref(0)
  const pagedRows = ref<T[]>([])
  const lastLengthRefreshAt = ref(0)
  let refreshLengthPromise: Promise<void> | null = null

  const pagination = reactive<PaginationState>({
    page: 1,
    pageCount: 1,
    pageSize,
    pageSlot: 5,
    prefix: ({ itemCount }) => `Total ${itemCount} ${itemLabel}`,
  })

  const updatePageCount = () => {
    pagination.pageCount = Math.max(
      1,
      Math.ceil(totalCount.value / pagination.pageSize),
    )
    pagination.itemCount = totalCount.value
  }

  const updateData = async (currentPage: number) => {
    const activeSortState = sortState?.value ?? null
    const useLiveRows =
      currentPage === 1 &&
      (shouldUseLiveRows ? shouldUseLiveRows(activeSortState) : true)
    if (useLiveRows) {
      pagedRows.value = liveRows.value
      return
    }

    const offset = (currentPage - 1) * pagination.pageSize
    const response = await fetchJson<{ result: unknown[] }>(
      pageEndpoint(offset, activeSortState),
    )
    pagedRows.value = normalizeRows(response.result ?? [])
  }

  const handlePageChange = async (currentPage: number) => {
    pagination.page = currentPage
    await updateData(currentPage)
  }

  const refreshLength = async (force = false) => {
    const now = Date.now()
    if (
      !force &&
      totalCount.value > 0 &&
      now - lastLengthRefreshAt.value < lengthRefreshIntervalMs
    ) {
      return
    }
    if (refreshLengthPromise) {
      await refreshLengthPromise
      return
    }

    refreshLengthPromise = (async () => {
      try {
        const response = await fetchJson<{ result: number }>(lengthEndpoint)
        totalCount.value = response.result
        updatePageCount()
        lastLengthRefreshAt.value = Date.now()
      } finally {
        refreshLengthPromise = null
      }
    })()

    await refreshLengthPromise
  }

  const refreshPageAfterDelete = async () => {
    await refreshLength(true)
    const maxPage = Math.max(1, pagination.pageCount || 1)
    if (pagination.page > maxPage) {
      pagination.page = maxPage
    }
    await updateData(pagination.page)
  }

  watch(
    liveRows,
    async () => {
      await refreshLength()
      if (pagination.page === 1) {
        await updateData(1)
      }
    },
    { immediate: true },
  )

  onMounted(async () => {
    await refreshLength(true)
  })

  if (sortState) {
    watch(
      sortState,
      async () => {
        pagination.page = 1
        await updateData(1)
      },
      { deep: true },
    )
  }

  return {
    pagedRows,
    pagination,
    handlePageChange,
    refreshLength,
    refreshPageAfterDelete,
  }
}
