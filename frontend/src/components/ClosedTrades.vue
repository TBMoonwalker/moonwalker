<template>
    <n-data-table
        remote
        ref="table"
        :columns="columns_closed_trades"
        :data="paged_closed_trades || []"
        :loading="isTableLoading"
        :row-class-name="row_classes"
        :pagination="pageReactive"
        :locale="{ emptyText: tableEmptyText }"
        aria-label="Closed trades table"
        @update:page="handlePageChange"
    />
</template>

<script setup lang="ts">
import { computed, h, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { NButton } from 'naive-ui/es/button'
import { NDataTable, type DataTableColumns } from 'naive-ui/es/data-table'
import { useDialog } from 'naive-ui/es/dialog'
import { useMessage } from 'naive-ui/es/message'
import { useWebSocketDataStore } from '../stores/websocket'
import { useTradesStore } from '../stores/trades'
import { storeToRefs } from 'pinia'
import { fetchJson } from '../api/client'
import { formatTradingViewDateParts } from '../helpers/date'
const closed_trade_store = useWebSocketDataStore("closedTrades")
const closed_trade_data = storeToRefs(closed_trade_store)
const trades_store = useTradesStore()
// Only fetch the 10 actual closed trades with websocket - other ones get with direct api call!!!
const closed_trades = ref()
const closed_trades_length = ref()
const paged_closed_trades = ref()
const LENGTH_REFRESH_INTERVAL_MS = 5000
const lastLengthRefreshAt = ref(0)
let refreshLengthPromise: Promise<void> | null = null
const pageReactive = reactive({
    page: 1,
    pageCount: 1,
    pageSize: 10,
    pageSlot: 5,
    prefix({ itemCount }) {
        return `Total ${itemCount} trades`
    }
});
const viewportWidth = ref(window.innerWidth)
const isMobile = computed(() => viewportWidth.value < 768)
const isTablet = computed(() => viewportWidth.value >= 768 && viewportWidth.value < 1200)
const isTableLoading = computed(
    () => !closed_trade_data.hasReceivedData.value && closed_trade_data.status.value !== 'CLOSED',
)
const tableEmptyText = computed(() => {
    if (!closed_trade_data.hasReceivedData.value) {
        return 'Waiting for live closed trades...'
    }
    return 'No closed trades'
})
const dialog = useDialog()
const message = useMessage()

const handleResize = () => {
    viewportWidth.value = window.innerWidth
}

const updatePageCount = () => {
    pageReactive.pageCount = Math.ceil(closed_trades_length.value / pageReactive.pageSize)
    pageReactive.itemCount = closed_trades_length.value
}

const updateData = async (currentPage: number) => {
    let pagination = 0
    if (currentPage == 1) {
        const data = closed_trades
        paged_closed_trades.value = data.value
    } else {
        pagination = (currentPage - 1) * pageReactive.pageSize
        const data = await fetchJson<{ result: RowData[] }>(`/trades/closed/${pagination}`)
        trades_store.setClosedTrades(data.result ?? [])
        paged_closed_trades.value = trades_store.closedTrades
    }

}

const handlePageChange = async (currentPage: number) => {
    pageReactive.page = currentPage
    await updateData(currentPage)
}

const refreshLength = async (force = false) => {
    const now = Date.now()
    if (
        !force &&
        closed_trades_length.value !== undefined &&
        now - lastLengthRefreshAt.value < LENGTH_REFRESH_INTERVAL_MS
    ) {
        return
    }
    if (refreshLengthPromise) {
        await refreshLengthPromise
        return
    }

    refreshLengthPromise = (async () => {
        try {
            const response = await fetchJson<{ result: number }>('/trades/closed/length')
            closed_trades_length.value = response.result
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
    const maxPage = Math.max(1, pageReactive.pageCount || 1)
    if (pageReactive.page > maxPage) {
        pageReactive.page = maxPage
    }
    await updateData(pageReactive.page)
}

// Get new order data
watch(closed_trade_data.data, async (newData) => {
    if (!Array.isArray(newData)) {
        closed_trades.value = []
        paged_closed_trades.value = []
        return
    }

    const websocket_data: RowData[] = newData as RowData[]
    trades_store.setClosedTrades(websocket_data)
    closed_trades.value = trades_store.closedTrades

    await refreshLength()
    if (pageReactive.page === 1) {
        await updateData(pageReactive.page)
    }

}, { immediate: true })

type RowData = {
    id: number
    symbol: string
    amount: number
    cost: number
    profit: number
    profit_percent: number
    so_count: number
    duration: string
    close_date: string
}

function formatFixed(value: unknown, decimals = 2): string {
    const parsed = Number(value)
    if (!Number.isFinite(parsed)) {
        return (0).toFixed(decimals)
    }
    return parsed.toFixed(decimals)
}

function formatAssetAmount(value: unknown, maxDecimals = 8): string {
    const parsed = Number(value)
    if (!Number.isFinite(parsed)) {
        return "0"
    }
    return parsed.toFixed(maxDecimals).replace(/\.?0+$/, "")
}

function resolveDateTime(value: string): { date: string; time: string } {
    const parts = formatTradingViewDateParts(value)
    if (parts.time) {
        return parts
    }
    const raw = String(value).trim()
    const match = raw.match(/^(.*)\s(\d{2}:\d{2}(?::\d{2})?)$/)
    if (!match) {
        return parts
    }
    return { date: match[1], time: match[2] }
}

function row_classes(row: RowData) {
    if (Math.sign(row.profit_percent) >= 0) {
        return 'green'
    } else {
        return 'red'
    }
}

async function handleDeleteClosedTrade(rowData: RowData): Promise<void> {
    const d = dialog.warning({
        title: 'Delete closed trade',
        content: `Delete ${rowData.symbol} from closed trades history? This cannot be undone.`,
        positiveText: 'Delete',
        negativeText: 'Cancel',
        onPositiveClick: async () => {
            d.loading = true
            try {
                const result = await fetchJson<{ result: string }>(`/trades/closed/delete/${rowData.id}`, {
                    method: 'POST'
                })
                if (result.result === 'deleted') {
                    message.success(`Deleted ${rowData.symbol}.`)
                    await refreshPageAfterDelete()
                    return
                }
                message.error(`Failed deleting ${rowData.symbol}.`)
            } catch (error) {
                const detail = error instanceof Error ? error.message : 'Unknown error'
                message.error(`Failed deleting ${rowData.symbol}: ${detail}`)
            }
        }
    })
}

const columns_trades = (): DataTableColumns<RowData> => {
    const columns: DataTableColumns<RowData> = [
        {
            title: '#',
            key: 'key',
            defaultSortOrder: 'ascend'
        },
        {
            title: 'Pair',
            key: 'symbol',
        },
        {
            title: 'Amount',
            key: 'amount',
            render: (rowData) => {
                return formatAssetAmount(rowData.amount)
            },
        },
        {
            title: 'Profit',
            key: 'profit',
            render: (rowData) => {
                return formatFixed(rowData.profit)
            },
        },
        {
            title: 'Cost',
            key: 'cost',
            render: (rowData) => {
                return formatFixed(rowData.cost)
            },
        },
        {
            title: 'PNL %',
            key: 'profit_percent',
            className: 'profit',
            render: (rowData) => {
                return `${formatFixed(rowData.profit_percent)} %`
            },
        },
        {
            title: 'SO',
            key: 'so_count',
            align: 'center'
        },
        {
            title: 'Duration',
            key: 'duration'
        },
        {
            title: 'Closed',
            key: 'close_date',
            render: (rowData) => {
                const { date, time } = resolveDateTime(rowData.close_date)
                return [
                    h('div', date),
                    h('div', time),
                ]
            },
        },
        {
            title: 'Action',
            key: 'action',
            align: 'center',
            render: (rowData) => {
                return h(
                    NButton,
                    {
                        size: 'small',
                        type: 'error',
                        ghost: true,
                        onClick: () => handleDeleteClosedTrade(rowData),
                    },
                    { default: () => 'Delete' }
                )
            },
        },
    ]

    if (isMobile.value) {
        return columns.filter((column) => {
            if (!("key" in column)) {
                return true
            }
            return ["symbol", "profit_percent", "close_date", "action"].includes(String(column.key))
        })
    }

    if (isTablet.value) {
        return columns.filter((column) => {
            if (!("key" in column)) {
                return true
            }
            return [
                "symbol",
                "amount",
                "profit",
                "profit_percent",
                "so_count",
                "close_date",
                "action",
            ].includes(String(column.key))
        })
    }

    return columns
}

const columns_closed_trades = computed(() => columns_trades())

onMounted(async () => {
    window.addEventListener('resize', handleResize)
    await refreshLength(true)
})

onUnmounted(() => {
    window.removeEventListener('resize', handleResize)
})

</script>

<style scoped>
:deep(.red .profit) {
    color: rgb(224, 108, 117) !important;
}

:deep(.green .profit) {
    color: rgb(99, 226, 183) !important;
}
</style>
