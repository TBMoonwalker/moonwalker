<template>
    <n-data-table remote ref="table" :columns="columns_closed_trades" :data="paged_closed_trades"
        :row-class-name="row_classes" :pagination="pageReactive" @update:page="handlePageChange" />
</template>

<script setup lang="ts">
import { MOONWALKER_API_PORT, MOONWALKER_API_HOST } from '../config'
import { ref, watch, reactive } from 'vue'
import { type DataTableColumns } from 'naive-ui'
import { useWebSocketDataStore } from '../stores/websocket'
import { storeToRefs } from 'pinia'
import { isFloat, isJsonString } from '../helpers/validators'
const closed_trade_store = useWebSocketDataStore("closedTrades")
const closed_trade_data = storeToRefs(closed_trade_store)
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
        const data = await fetch(`http://${MOONWALKER_API_HOST}:${MOONWALKER_API_PORT}/trades/closed/${pagination}`).then((response) =>
            response.json()
        )

        paged_closed_trades.value = await convertData(data)
    }

}

async function convertData(data: any) {
    const convert_data = ref(data)
    data.forEach(function (val: any, i: any) {
        var amount_length = 0
        if (isFloat(val.amount)) {
            amount_length = convert_data.value[i].amount.toString().split('.')[1].length
        }

        convert_data.value[i].cost = val.cost.toFixed(2)
        convert_data.value[i].profit = val.profit.toFixed(2)
        convert_data.value[i].profit_percent = val.profit_percent.toFixed(2)
        convert_data.value[i].amount = val.amount.toFixed(amount_length)
        convert_data.value[i].key = val.id
        let timestamp: number = Date.parse(val.close_date)
        let date = new Date(timestamp)
        convert_data.value[i].close_date = date.toLocaleString()

        if (isJsonString(convert_data.value[i].duration)) {
            const duration = JSON.parse(convert_data.value[i].duration)
            if (duration['days'] != 0) {
                convert_data.value[i].duration = duration['days'] + " days"
            } else if (duration['days'] == 0 && duration['hours'] != 0) {
                convert_data.value[i].duration = duration['hours'] + " hours"
            } else if (duration['hours'] == 0 && duration['minutes'] != 0) {
                convert_data.value[i].duration = duration['minutes'] + " minutes"
            } else if (duration['minutes'] == 0 && duration['seconds'] != 0) {
                convert_data.value[i].duration = duration['seconds'] + " seconds"
            }
        } else {
            convert_data.value[i].duration = "na"
        }

    })

    return data
}

const handlePageChange = async (currentPage: any) => {
    pageReactive.page = currentPage
    updateData(currentPage)
}

// Get new order data
watch(closed_trade_data.json, async (newData) => {
    if (newData !== undefined) {
        const websocket_data: RowData[] = JSON.parse(newData)
        closed_trades.value = websocket_data
        closed_trades.value = await convertData(websocket_data)

        // Get actual closed orders length to calculate pagination
        closed_trades_length.value = await fetch(`http://${MOONWALKER_API_HOST}:${MOONWALKER_API_PORT}/trades/closed/length`).then((response) =>
            response.json()
        )
        updatePageCount()
        updateData(pageReactive.page)
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
