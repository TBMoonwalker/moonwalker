<template>
    <div class="unsellable-trades">
        <div class="unsellable-trades-toolbar">
            <div class="unsellable-trades-summary">
                {{ unsellableTradesSummary }}
            </div>
            <n-button
                size="small"
                type="warning"
                ghost
                :disabled="unsellableTradesCount === 0"
                @click="handleResolveAllUnsellableTrades"
            >
                Resolve all
            </n-button>
        </div>
        <n-data-table
            remote
            ref="table"
            :columns="columns_unsellable_trades"
            :data="displayed_unsellable_trades || []"
            :loading="isTableLoading"
            :row-class-name="row_classes"
            :locale="{ emptyText: tableEmptyText }"
            aria-label="Unsellable trades table"
            @update:sorter="handleSorterChange"
        />
    </div>
</template>

<script setup lang="ts">
import { computed, h, ref } from 'vue'
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
    resolveTradeTableColumnOrder,
    resolveTradeDateTime,
    resolveTradeTableSortState,
    sortTradeRows,
    type TradeTableSortState,
} from '../helpers/tradeTable'
import {
    useTradesStore,
    type UnsellableTradeRow,
} from '../stores/trades'
import { useWebSocketDataStore } from '../stores/websocket'

const trades_store = useTradesStore()
const unsellable_trades_socket_store = useWebSocketDataStore('unsellableTrades')
const { isMobile, isTablet } = useViewport()
const dialog = useDialog()
const message = useMessage()
const sortState = ref<TradeTableSortState | null>(null)

const {
    rows: unsellable_trades,
    isTableLoading,
    tableEmptyText,
} = useTradeTableFeed<UnsellableTradeRow>({
    websocketId: 'unsellableTrades',
    waitingText: 'Waiting for live unsellable trades...',
    emptyText: 'No unsellable trades',
    normalizeRows: (rawRows) => {
        trades_store.setUnsellableTrades(rawRows as any[])
        return trades_store.unsellableTrades as UnsellableTradeRow[]
    },
})
const displayed_unsellable_trades = computed(() =>
    sortTradeRows(unsellable_trades.value, sortState.value, {
        id: { kind: 'number', value: (row) => row.id },
        symbol: { kind: 'text', value: (row) => row.symbol },
        amount: { kind: 'number', value: (row) => row.amount },
        cost: { kind: 'number', value: (row) => row.cost },
        profit_percent: { kind: 'number', value: (row) => row.profit_percent },
        unsellable_reason: {
            kind: 'text',
            value: (row) => row.unsellable_reason ?? '',
        },
        open_date: { kind: 'date', value: (row) => row.open_date },
        unsellable_since: {
            kind: 'date',
            value: (row) => row.unsellable_since ?? '',
        },
    }),
)

const unsellableTradesCount = computed(() => unsellable_trades.value.length)
const unsellableTradesSummary = computed(() => {
    const count = unsellableTradesCount.value
    if (count === 0) {
        return 'No unsellable trades'
    }
    if (count === 1) {
        return '1 unsellable trade is waiting for manual cleanup'
    }
    return `${count} unsellable trades are waiting for manual cleanup`
})

function row_classes(_row: UnsellableTradeRow) {
    return 'orange'
}

function toUnsellableSocketRow(
    rowData: UnsellableTradeRow,
): Record<string, unknown> {
    return {
        ...rowData,
        id: Number(rowData.id),
        amount: Number(rowData.amount),
        cost: Number(rowData.cost),
        profit: Number(rowData.profit),
        profit_percent: Number(rowData.profit_percent),
        so_count: Number(rowData.so_count),
        current_price: Number(rowData.current_price),
        avg_price: Number(rowData.avg_price),
    }
}

function syncUnsellableRows(nextRows: UnsellableTradeRow[]): void {
    unsellable_trades_socket_store.setRaw(
        JSON.stringify(nextRows.map(toUnsellableSocketRow)),
    )
}

function getStateLabel(rowData: UnsellableTradeRow): string {
    const reason = String(rowData.unsellable_reason ?? 'unknown').replaceAll('_', ' ')
    if (reason === 'minimum notional') {
        return 'Below minimum notional'
    }
    return reason
}

function getStateDetail(rowData: UnsellableTradeRow): string {
    const details: string[] = [getStateLabel(rowData)]
    if (rowData.unsellable_estimated_notional !== null && rowData.unsellable_estimated_notional !== undefined) {
        details.push(`est. ${formatFixed(rowData.unsellable_estimated_notional)}`)
    }
    if (rowData.unsellable_min_notional !== null && rowData.unsellable_min_notional !== undefined) {
        details.push(`min ${formatFixed(rowData.unsellable_min_notional)}`)
    }
    return details.join(' | ')
}

function handleSorterChange(sorter: unknown): void {
    sortState.value = resolveTradeTableSortState(sorter)
}

async function handleResolveAllUnsellableTrades(): Promise<void> {
    const count = unsellableTradesCount.value
    if (count === 0) {
        message.info('No unsellable trades to resolve.')
        return
    }

    const d = dialog.warning({
        title: 'Resolve all unsellable trades',
        content: `Remove all ${count} unsellable trades from the list after manual exchange cleanup?`,
        positiveText: 'Resolve all',
        negativeText: 'Cancel',
        onPositiveClick: async () => {
            d.loading = true
            try {
                const result = await fetchJson<{ result: string; count: number }>(
                    '/trades/unsellable/delete/all',
                    { method: 'POST' },
                )
                if (result.result === 'deleted') {
                    syncUnsellableRows([])
                    message.success(`Resolved ${result.count} unsellable trades.`)
                    return
                }
                message.error('Failed resolving all unsellable trades.')
            } catch (error) {
                const detail = error instanceof Error ? error.message : 'Unknown error'
                message.error(`Failed resolving all unsellable trades: ${detail}`)
            }
        },
    })
}

async function handleResolveUnsellableTrade(
    rowData: UnsellableTradeRow,
): Promise<void> {
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
                    syncUnsellableRows(
                        unsellable_trades.value.filter(
                            (trade) => Number(trade.id) !== Number(rowData.id),
                        ),
                    )
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

const columns_trades = (): DataTableColumns<UnsellableTradeRow> => {
    const columns: DataTableColumns<UnsellableTradeRow> = [
        {
            title: '#',
            key: 'id',
            sorter: true,
            sortOrder: resolveTradeTableColumnOrder(sortState.value, 'id'),
        },
        {
            title: 'Pair',
            key: 'symbol',
            sorter: true,
            sortOrder: resolveTradeTableColumnOrder(sortState.value, 'symbol'),
        },
        {
            title: 'Amount',
            key: 'amount',
            render: (rowData) => formatAssetAmount(rowData.amount),
            sorter: true,
            sortOrder: resolveTradeTableColumnOrder(sortState.value, 'amount'),
        },
        {
            title: 'Cost',
            key: 'cost',
            render: (rowData) => formatFixed(rowData.cost),
            sorter: true,
            sortOrder: resolveTradeTableColumnOrder(sortState.value, 'cost'),
        },
        {
            title: 'PNL %',
            key: 'profit_percent',
            render: (rowData) => `${formatFixed(rowData.profit_percent)} %`,
            sorter: true,
            sortOrder: resolveTradeTableColumnOrder(
                sortState.value,
                'profit_percent',
            ),
        },
        {
            title: 'State',
            key: 'unsellable_reason',
            render: (rowData) => getStateDetail(rowData),
            sorter: true,
            sortOrder: resolveTradeTableColumnOrder(
                sortState.value,
                'unsellable_reason',
            ),
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
            sorter: true,
            sortOrder: resolveTradeTableColumnOrder(
                sortState.value,
                'open_date',
            ),
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
            sorter: true,
            sortOrder: resolveTradeTableColumnOrder(
                sortState.value,
                'unsellable_since',
            ),
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

<style scoped>
.unsellable-trades {
    display: flex;
    flex-direction: column;
    gap: 12px;
}

.unsellable-trades-toolbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 16px 16px 0;
}

.unsellable-trades-summary {
    color: inherit;
    font-size: 14px;
    line-height: 1.4;
    opacity: 0.82;
}

@media (max-width: 768px) {
    .unsellable-trades-toolbar {
        flex-direction: column;
        align-items: stretch;
        padding: 12px 12px 0;
    }

    .unsellable-trades-summary {
        font-size: 13px;
    }
}
</style>
