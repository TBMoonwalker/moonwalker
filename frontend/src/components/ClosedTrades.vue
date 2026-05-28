<template>
    <n-data-table
        remote
        ref="table"
        :columns="columns_closed_trades"
        :data="paged_closed_trades || []"
        :loading="isTableLoading"
        :row-class-name="row_classes"
        :render-expand-icon="renderExpandIcon"
        :pagination="pageReactive"
        :locale="{ emptyText: tableEmptyText }"
        aria-label="Closed trades table"
        @update:page="handlePageChange"
        @update:sorter="handleSorterChange"
    />
</template>

<script setup lang="ts">
import { computed, h, onMounted, ref } from 'vue'
import { ArrowForwardCircleOutline } from '@vicons/ionicons5'
import { NButton } from 'naive-ui/es/button'
import { NDataTable, type DataTableColumns } from 'naive-ui/es/data-table'
import { useDialog } from 'naive-ui/es/dialog'
import { NIcon } from 'naive-ui/es/icon'
import { useMessage } from 'naive-ui/es/message'
import ClosedTradeExpandedRow from './ClosedTradeExpandedRow.vue'
import { fetchJson } from '../api/client'
import { useConfiguredMinTimeframe } from '../composables/useConfiguredMinTimeframe'
import { usePagedTradeFeed } from '../composables/usePagedTradeFeed'
import { useTradeTableFeed } from '../composables/useTradeTableFeed'
import { useViewport } from '../composables/useViewport'
import {
    CLOSED_TRADES_MOBILE_COLUMN_KEYS,
    CLOSED_TRADES_TABLET_COLUMN_KEYS,
    formatAssetAmount,
    formatFixed,
    resolveTradeTableColumnOrder,
    resolveTradeDateTime,
    resolveTradeTableSortState,
    shouldShowTradeTableColumn,
    type TradeTableSortState,
} from '../helpers/tradeTable'
import { useTradesStore, type ClosedTradeRow } from '../stores/trades'

const trades_store = useTradesStore()
const { isMobile, isTablet } = useViewport()
const { configuredMinTimeframe, loadConfiguredMinTimeframe } =
    useConfiguredMinTimeframe()
const dialog = useDialog()
const message = useMessage()
const sortState = ref<TradeTableSortState | null>(null)

const {
    rows: closed_trades,
    isTableLoading,
    tableEmptyText,
} = useTradeTableFeed<ClosedTradeRow>({
    websocketId: 'closedTrades',
    waitingText: 'Waiting for live closed trades...',
    emptyText: 'No closed trades',
    normalizeRows: (rawRows) => {
        trades_store.setClosedTrades(rawRows as any[])
        return trades_store.closedTrades as ClosedTradeRow[]
    },
})

const {
    pagedRows: paged_closed_trades,
    pagination: pageReactive,
    handlePageChange,
    refreshPageAfterDelete,
} = usePagedTradeFeed<ClosedTradeRow>({
    liveRows: closed_trades,
    normalizeRows: (rawRows) => {
        trades_store.setClosedTrades(rawRows as any[])
        return trades_store.closedTrades as ClosedTradeRow[]
    },
    lengthEndpoint: '/trades/closed/length',
    pageEndpoint: (offset, activeSortState) => {
        const query = new URLSearchParams()
        if (activeSortState) {
            query.set('sort_key', activeSortState.columnKey)
            query.set(
                'sort_dir',
                activeSortState.order === 'ascend' ? 'asc' : 'desc',
            )
        }
        const suffix = query.toString()
        return suffix
            ? `/trades/closed/${offset}?${suffix}`
            : `/trades/closed/${offset}`
    },
    itemLabel: 'trades',
    sortState,
    shouldUseLiveRows: (activeSortState) => activeSortState === null,
})

function row_classes(row: ClosedTradeRow) {
    if (Math.sign(row.profit_percent) >= 0) {
        return 'green'
    } else {
        return 'red'
    }
}

async function handleDeleteClosedTrade(rowData: ClosedTradeRow): Promise<void> {
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

function renderExpandIcon() {
    return h(
        NIcon,
        { size: 24, color: '#63e2b7' },
        { default: () => h(ArrowForwardCircleOutline) },
    )
}

function handleSorterChange(sorter: unknown): void {
    sortState.value = resolveTradeTableSortState(sorter)
}

function formatCloseReason(reason: string | null | undefined): string {
    switch (reason) {
        case 'sidestep_exit':
            return 'Sidestep exit'
        case 'trailing_take_profit':
            return 'Trailing TP'
        case 'take_profit':
            return 'Take profit'
        case 'manual_sell':
            return 'Manual sell'
        case 'manual_stop':
            return 'Manual stop'
        case 'stop_loss':
            return 'Stop loss'
        case 'autopilot_timeout':
            return 'Autopilot timeout'
        default:
            return 'Take profit'
    }
}

const columns_trades = (): DataTableColumns<ClosedTradeRow> => {
    const columns: DataTableColumns<ClosedTradeRow> = [
        {
            type: 'expand',
            expandable: () => true,
            renderExpand: (rowData) =>
                h(ClosedTradeExpandedRow, {
                    rowData,
                    minTimeframe: configuredMinTimeframe.value,
                }),
        },
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
            render: (rowData) => {
                return formatAssetAmount(rowData.amount)
            },
            sorter: true,
            sortOrder: resolveTradeTableColumnOrder(sortState.value, 'amount'),
        },
        {
            title: 'Profit',
            key: 'profit',
            render: (rowData) => {
                return formatFixed(rowData.profit)
            },
            sorter: true,
            sortOrder: resolveTradeTableColumnOrder(sortState.value, 'profit'),
        },
        {
            title: 'Cost',
            key: 'cost',
            render: (rowData) => {
                return formatFixed(rowData.cost)
            },
            sorter: true,
            sortOrder: resolveTradeTableColumnOrder(sortState.value, 'cost'),
        },
        {
            title: 'PNL %',
            key: 'profit_percent',
            className: 'profit',
            render: (rowData) => {
                return `${formatFixed(rowData.profit_percent)} %`
            },
            sorter: true,
            sortOrder: resolveTradeTableColumnOrder(
                sortState.value,
                'profit_percent',
            ),
        },
        {
            title: 'SO',
            key: 'so_count',
            align: 'center',
            sorter: true,
            sortOrder: resolveTradeTableColumnOrder(sortState.value, 'so_count'),
        },
        {
            title: 'Outcome',
            key: 'close_reason',
            render: (rowData) => formatCloseReason(rowData.close_reason),
            sorter: true,
            sortOrder: resolveTradeTableColumnOrder(
                sortState.value,
                'close_reason',
            ),
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
            sorter: true,
            sortOrder: resolveTradeTableColumnOrder(
                sortState.value,
                'close_date',
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
            return shouldShowTradeTableColumn(
                column.key,
                CLOSED_TRADES_MOBILE_COLUMN_KEYS,
            )
        })
    }

    if (isTablet.value) {
        return columns.filter((column) => {
            if (!("key" in column)) {
                return true
            }
            return shouldShowTradeTableColumn(
                column.key,
                CLOSED_TRADES_TABLET_COLUMN_KEYS,
            )
        })
    }

    return columns
}

const columns_closed_trades = computed(() => columns_trades())

onMounted(async () => {
    await loadConfiguredMinTimeframe()
})

</script>

<style scoped>
:deep(.red .profit) {
    color: #B4443F !important;
}

:deep(.green .profit) {
    color: #2E7D5B !important;
}

:deep(.n-data-table-expand-trigger) {
    height: 16px;
}
</style>
