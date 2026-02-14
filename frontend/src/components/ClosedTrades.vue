<template>
    <n-data-table remote ref="table" :columns="columns_closed_trades" :data="paged_closed_trades"
        :row-class-name="row_classes" :pagination="pageReactive" @update:page="handlePageChange" />
</template>

<script setup lang="ts">
import { computed, h, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { NButton, type DataTableColumns, NDataTable, useDialog, useMessage } from 'naive-ui'
import { useWebSocketDataStore } from '../stores/websocket'
import { useTradesStore } from '../stores/trades'
import { storeToRefs } from 'pinia'
import { fetchJson } from '../api/client'
const closed_trade_store = useWebSocketDataStore("closedTrades")
const closed_trade_data = storeToRefs(closed_trade_store)
const trades_store = useTradesStore()
// Only fetch the 10 actual closed trades with websocket - other ones get with direct api call!!!
const closed_trades = ref()
const closed_trades_length = ref()
const paged_closed_trades = ref()
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

const handlePageChange = async (currentPage: any) => {
    pageReactive.page = currentPage
    updateData(currentPage)
}

const refreshLength = async () => {
    const response = await fetchJson<{ result: number }>('/trades/closed/length')
    closed_trades_length.value = response.result
    updatePageCount()
}

const refreshPageAfterDelete = async () => {
    await refreshLength()
    const maxPage = Math.max(1, pageReactive.pageCount || 1)
    if (pageReactive.page > maxPage) {
        pageReactive.page = maxPage
    }
    await updateData(pageReactive.page)
}

// Get new order data
watch(closed_trade_data.data, async (newData) => {
    if (newData !== undefined) {
        const websocket_data: RowData[] = newData as RowData[]
        trades_store.setClosedTrades(websocket_data)
        closed_trades.value = trades_store.closedTrades

        await refreshLength()
        if (pageReactive.page === 1) {
            updateData(pageReactive.page)
        }
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
            key: 'amount'
        },
        {
            title: 'Profit',
            key: 'profit',
            render: (rowData) => {
                return Number(rowData.profit ?? 0).toFixed(2)
            },
        },
        {
            title: 'Cost',
            key: 'cost',
        },
        {
            title: 'PNL %',
            key: 'profit_percent',
            className: 'profit',
            render: (rowData) => {
                return `${Number(rowData.profit_percent ?? 0).toFixed(2)} %`
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
            key: 'close_date'
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
    await refreshLength()
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
