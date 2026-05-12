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
    />
</template>

<script setup lang="ts">
import { computed, h, onMounted } from 'vue'
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
    formatAssetAmount,
    formatFixed,
    resolveTradeDateTime,
} from '../helpers/tradeTable'
import { useTradesStore, type ClosedTradeRow } from '../stores/trades'

const trades_store = useTradesStore()
const { isMobile, isTablet } = useViewport()
const { configuredMinTimeframe, loadConfiguredMinTimeframe } =
    useConfiguredMinTimeframe()
const dialog = useDialog()
const message = useMessage()

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
    pageEndpoint: (offset) => `/trades/closed/${offset}`,
    itemLabel: 'trades',
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
            title: 'Outcome',
            key: 'close_reason',
            render: (rowData) => formatCloseReason(rowData.close_reason),
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
                "close_reason",
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
    await loadConfiguredMinTimeframe()
})

</script>

<style scoped>
:deep(.red .profit) {
    color: rgb(224, 108, 117) !important;
}

:deep(.green .profit) {
    color: rgb(99, 226, 183) !important;
}

:deep(.n-data-table-expand-trigger) {
    height: 16px;
}
</style>
