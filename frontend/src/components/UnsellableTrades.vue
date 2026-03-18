<template>
    <n-data-table
        remote
        ref="table"
        :columns="columns_unsellable_trades"
        :data="unsellable_trades || []"
        :loading="isTableLoading"
        :row-class-name="row_classes"
        :locale="{ emptyText: tableEmptyText }"
        aria-label="Unsellable trades table"
    />
</template>

<script setup lang="ts">
import { computed, h } from 'vue'
import { NButton } from 'naive-ui/es/button'
import { NDataTable, type DataTableColumns } from 'naive-ui/es/data-table'
import { useDialog } from 'naive-ui/es/dialog'
import { useMessage } from 'naive-ui/es/message'
import { fetchJson } from '../api/client'
import { useTradeTableFeed } from '../composables/useTradeTableFeed'
import { useViewport } from '../composables/useViewport'
import {
    formatAssetAmount,
    formatFixed,
    resolveTradeDateTime,
} from '../helpers/tradeTable'
import { useTradesStore } from '../stores/trades'

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
    current_price: number
    avg_price: number
    open_date: string
    unsellable_reason?: string | null
    unsellable_min_notional?: number | null
    unsellable_estimated_notional?: number | null
    unsellable_since?: string | null
}

const {
    rows: unsellable_trades,
    isTableLoading,
    tableEmptyText,
} = useTradeTableFeed<RowData>({
    websocketId: 'unsellableTrades',
    waitingText: 'Waiting for live unsellable trades...',
    emptyText: 'No unsellable trades',
    normalizeRows: (rawRows) => {
        trades_store.setUnsellableTrades(rawRows as any[])
        return trades_store.unsellableTrades as RowData[]
    },
})

function row_classes(_row: RowData) {
    return 'orange'
}

function getStateLabel(rowData: RowData): string {
    const reason = String(rowData.unsellable_reason ?? 'unknown').replaceAll('_', ' ')
    if (reason === 'minimum notional') {
        return 'Below minimum notional'
    }
    return reason
}

function getStateDetail(rowData: RowData): string {
    const details: string[] = [getStateLabel(rowData)]
    if (rowData.unsellable_estimated_notional !== null && rowData.unsellable_estimated_notional !== undefined) {
        details.push(`est. ${formatFixed(rowData.unsellable_estimated_notional)}`)
    }
    if (rowData.unsellable_min_notional !== null && rowData.unsellable_min_notional !== undefined) {
        details.push(`min ${formatFixed(rowData.unsellable_min_notional)}`)
    }
    return details.join(' | ')
}

async function handleResolveUnsellableTrade(rowData: RowData): Promise<void> {
    const d = dialog.warning({
        title: 'Resolve unsellable trade',
        content: `Remove ${rowData.symbol} from the unsellable list after manual exchange cleanup?`,
        positiveText: 'Resolve',
        negativeText: 'Cancel',
        onPositiveClick: async () => {
            d.loading = true
            try {
                const result = await fetchJson<{ result: string }>(
                    `/trades/unsellable/delete/${rowData.id}`,
                    { method: 'POST' }
                )
                if (result.result === 'deleted') {
                    message.success(`Resolved ${rowData.symbol}.`)
                    return
                }
                message.error(`Failed resolving ${rowData.symbol}.`)
            } catch (error) {
                const detail = error instanceof Error ? error.message : 'Unknown error'
                message.error(`Failed resolving ${rowData.symbol}: ${detail}`)
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
            render: (rowData) => formatAssetAmount(rowData.amount),
        },
        {
            title: 'Cost',
            key: 'cost',
            render: (rowData) => formatFixed(rowData.cost),
        },
        {
            title: 'PNL %',
            key: 'profit_percent',
            render: (rowData) => `${formatFixed(rowData.profit_percent)} %`,
        },
        {
            title: 'State',
            key: 'unsellable_reason',
            render: (rowData) => getStateDetail(rowData),
        },
        {
            title: 'Opened',
            key: 'open_date',
            render: (rowData) => {
                const { date, time } = resolveTradeDateTime(rowData.open_date)
                return [
                    h('div', date),
                    h('div', time),
                ]
            },
        },
        {
            title: 'Flagged',
            key: 'unsellable_since',
            render: (rowData) => {
                const { date, time } = resolveTradeDateTime(String(rowData.unsellable_since ?? ''))
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
                        type: 'warning',
                        ghost: true,
                        onClick: () => handleResolveUnsellableTrade(rowData),
                    },
                    { default: () => 'Resolve' }
                )
            },
        },
    ]

    if (isMobile.value) {
        return columns.filter((column) => {
            if (!("key" in column)) {
                return true
            }
            return ["symbol", "amount", "unsellable_reason", "action"].includes(String(column.key))
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
                "cost",
                "profit_percent",
                "unsellable_reason",
                "action",
            ].includes(String(column.key))
        })
    }

    return columns
}

const columns_unsellable_trades = computed(() => columns_trades())
</script>
