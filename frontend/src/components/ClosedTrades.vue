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
import { computed, h } from 'vue'
import { NButton } from 'naive-ui/es/button'
import { NDataTable, type DataTableColumns } from 'naive-ui/es/data-table'
import { useDialog } from 'naive-ui/es/dialog'
import { useMessage } from 'naive-ui/es/message'
import { useTradesStore } from '../stores/trades'
import { fetchJson } from '../api/client'
import { usePagedTradeFeed } from '../composables/usePagedTradeFeed'
import { useTradeTableFeed } from '../composables/useTradeTableFeed'
import { useViewport } from '../composables/useViewport'
import {
    formatAssetAmount,
    formatFixed,
    resolveTradeDateTime,
} from '../helpers/tradeTable'

const trades_store = useTradesStore()
const { isMobile, isTablet } = useViewport()
const dialog = useDialog()
const message = useMessage()

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

const {
    rows: closed_trades,
    isTableLoading,
    tableEmptyText,
} = useTradeTableFeed<RowData>({
    websocketId: 'closedTrades',
    waitingText: 'Waiting for live closed trades...',
    emptyText: 'No closed trades',
    normalizeRows: (rawRows) => {
        trades_store.setClosedTrades(rawRows as any[])
        return trades_store.closedTrades as RowData[]
    },
})

const {
    pagedRows: paged_closed_trades,
    pagination: pageReactive,
    handlePageChange,
    refreshPageAfterDelete,
} = usePagedTradeFeed<RowData>({
    liveRows: closed_trades,
    normalizeRows: (rawRows) => {
        trades_store.setClosedTrades(rawRows as any[])
        return trades_store.closedTrades as RowData[]
    },
    lengthEndpoint: '/trades/closed/length',
    pageEndpoint: (offset) => `/trades/closed/${offset}`,
    itemLabel: 'trades',
})

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
                const { date, time } = resolveTradeDateTime(rowData.close_date)
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

</script>

<style scoped>
:deep(.red .profit) {
    color: rgb(224, 108, 117) !important;
}

:deep(.green .profit) {
    color: rgb(99, 226, 183) !important;
}
</style>
