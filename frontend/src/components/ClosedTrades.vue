<template>
    <n-data-table remote ref="table" :columns="columns_closed_trades" :data="paged_closed_trades"
        :row-class-name="row_classes" :pagination="pageReactive" @update:page="handlePageChange" />
</template>

<script setup lang="ts">
import { onMounted, ref, watch, reactive } from 'vue'
import { type DataTableColumns, NDataTable } from 'naive-ui'
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
    if (closed_trades_length.value !== undefined) {
        return
    }
    const response = await fetchJson<{ result: number }>('/trades/closed/length')
    closed_trades_length.value = response.result
    updatePageCount()
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

onMounted(async () => {
    await refreshLength()
})

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

const columns_trades = (): DataTableColumns<RowData> => {
    return [
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
        },
        {
            title: 'Cost',
            key: 'cost',
        },
        {
            title: 'PNL %',
            key: 'profit_percent',
            className: 'profit',
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
    ]
}

const columns_closed_trades = columns_trades()

</script>

<style scoped>
:deep(.red .profit) {
    color: rgb(224, 108, 117) !important;
}

:deep(.green .profit) {
    color: rgb(99, 226, 183) !important;
}
</style>
