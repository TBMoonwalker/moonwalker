<template>
    <n-data-table
        size="small"
        remote
        ref="table"
        :columns="columns_open_trades"
        :data="displayed_open_trades || []"
        :loading="isTableLoading"
        :row-class-name="row_classes"
        :row-key="getOpenTradeRowKey"
        :row-props="getOpenTradeRowProps"
        v-model:expanded-row-keys="expandedTradeRowKeys"
        :locale="{ emptyText: tableEmptyText }"
        aria-label="Open trades table"
        @update:sorter="handleSorterChange"
    />
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
    NDataTable,
    type DataTableRowKey,
} from 'naive-ui/es/data-table'
import { useDialog } from 'naive-ui/es/dialog'
import { useMessage } from 'naive-ui/es/message'
import { useWebSocketDataStore } from '../stores/websocket'
import { useTradesStore } from '../stores/trades'
import { storeToRefs } from 'pinia'
import { useSharedConfigSnapshot } from '../control-center/configSnapshotStore'
import { useConfiguredMinTimeframe } from '../composables/useConfiguredMinTimeframe'
import { useMissionPauseActions } from '../composables/useMissionPauseActions'
import { useOpenTradeActions } from '../composables/useOpenTradeActions'
import { useOpenTradeColumns } from '../composables/useOpenTradeColumns'
import { useTradeTableFeed } from '../composables/useTradeTableFeed'
import { useViewport } from '../composables/useViewport'
import {
    getOpenTradeOpenedAt,
    toFiniteNonNegative,
    type OpenTradeRow,
} from '../helpers/openTrades'
import {
    resolveTradeTableSortState,
    sortTradeRows,
    type TradeTableSortState,
} from '../helpers/tradeTable'

const props = withDefaults(
    defineProps<{
        globalTradingPaused?: boolean
    }>(),
    {
        globalTradingPaused: false,
    },
)

const statistics_store = useWebSocketDataStore("statistics")
const statistics_data = storeToRefs(statistics_store)
const trades_store = useTradesStore()

const dialog = useDialog()
const message = useMessage()

const { isMobile, isTablet } = useViewport()
const configSnapshotStore = useSharedConfigSnapshot()
const { configuredMinTimeframe, loadConfiguredMinTimeframe } =
    useConfiguredMinTimeframe()
const sortState = ref<TradeTableSortState | null>(null)
const expandedTradeRowKeys = ref<DataTableRowKey[]>([])

const {
    rows: open_trades,
    isTableLoading,
    tableEmptyText,
} = useTradeTableFeed<OpenTradeRow>({
    websocketId: 'openTrades',
    waitingText: 'Waiting for live open trades...',
    emptyText: 'No open trades',
    normalizeRows: (rawRows) => {
        trades_store.setOpenTrades(rawRows as any[])
        return trades_store.openTrades as OpenTradeRow[]
    },
})
const displayed_open_trades = computed(() =>
    sortTradeRows(open_trades.value, sortState.value, {
        symbol: {
            kind: 'text',
            value: (row) => row.symbol,
        },
        cost: {
            kind: 'number',
            value: (row) => row.cost,
        },
        display_profit_percent: {
            kind: 'number',
            value: (row) => row.display_profit_percent ?? row.profit_percent,
        },
        so_count: {
            kind: 'number',
            value: (row) => row.so_count,
        },
        open_date: {
            kind: 'date',
            value: (row) => getOpenTradeOpenedAt(row),
        },
    }),
)

const availableFunds = computed(() => {
    const payload = statistics_data.data.value as Record<string, unknown> | null
    return toFiniteNonNegative(payload?.funds_available)
})
const maxSafetyOrders = computed(() =>
    Math.trunc(toFiniteNonNegative(configSnapshotStore.snapshot.value?.mstc)),
)
const {
    handleAddManualBuy,
    handleDealSell,
    handleDealStop,
} = useOpenTradeActions({
    availableFunds,
    dialog,
    message,
})
const {
    handlePauseMission,
    handleResumeMission,
    isMissionActionLoading,
    missionActionErrors,
} = useMissionPauseActions({
    message,
})

const {
    columnsOpenTrades: columns_open_trades,
    rowClasses: row_classes,
} = useOpenTradeColumns({
    configuredMinTimeframe,
    globalTradingPaused: computed(() => Boolean(props.globalTradingPaused)),
    isMobile,
    isMissionActionLoading,
    isTablet,
    missionActionErrors,
    onAddManualBuy: handleAddManualBuy,
    onDealSell: handleDealSell,
    onDealStop: handleDealStop,
    onPauseMission: (rowData) => handlePauseMission(rowData.symbol),
    onResumeMission: (rowData) => handleResumeMission(rowData.symbol),
    sortState,
    maxSafetyOrders,
})

function handleSorterChange(sorter: unknown): void {
    sortState.value = resolveTradeTableSortState(sorter)
}

function getOpenTradeRowKey(rowData: OpenTradeRow): DataTableRowKey {
    return rowData.deal_id || rowData.campaign_id || rowData.id
}

function isInteractiveRowTarget(target: EventTarget | null): boolean {
    if (!(target instanceof Element)) {
        return false
    }
    return Boolean(
        target.closest(
            [
                'a',
                'button',
                'input',
                'select',
                'textarea',
                '[contenteditable="true"]',
                '[role="button"]',
                '[role="menuitem"]',
                '.n-button',
                '.n-base-selection',
                '.n-checkbox',
                '.n-dropdown',
                '.n-input',
                '.n-switch',
            ].join(','),
        ),
    )
}

function toggleOpenTradeRow(rowData: OpenTradeRow): void {
    if (!rowData.symbol) {
        return
    }
    const rowKey = getOpenTradeRowKey(rowData)
    expandedTradeRowKeys.value = expandedTradeRowKeys.value.includes(rowKey)
        ? expandedTradeRowKeys.value.filter((key) => key !== rowKey)
        : [...expandedTradeRowKeys.value, rowKey]
}

function getOpenTradeRowProps(rowData: OpenTradeRow) {
    const rowKey = getOpenTradeRowKey(rowData)
    return {
        class: 'trade-row-clickable',
        tabindex: 0,
        'aria-expanded': expandedTradeRowKeys.value.includes(rowKey),
        'aria-label': `Toggle trade details for ${rowData.symbol}`,
        onClick: (event: MouseEvent) => {
            if (!isInteractiveRowTarget(event.target)) {
                toggleOpenTradeRow(rowData)
            }
        },
        onKeydown: (event: KeyboardEvent) => {
            if (
                (event.key === 'Enter' || event.key === ' ') &&
                !isInteractiveRowTarget(event.target)
            ) {
                event.preventDefault()
                toggleOpenTradeRow(rowData)
            }
        },
    }
}

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

:deep(.trade-row-clickable) {
    cursor: pointer;
}

:deep(.trade-row-clickable:focus-visible) {
    outline: 2px solid var(--mw-color-primary);
    outline-offset: -2px;
}

:deep(.n-data-table-table) {
    table-layout: fixed;
    width: 100%;
}

:deep(.trade-hidden-expand-cell),
:deep(.n-data-table-td--expand) {
    width: 0 !important;
    min-width: 0 !important;
    max-width: 0 !important;
    padding: 0 !important;
    border: 0 !important;
    overflow: hidden;
}

:deep(.n-data-table-table colgroup col:first-child) {
    width: 0 !important;
    min-width: 0 !important;
    max-width: 0 !important;
}

:deep(.trade-hidden-expand-cell .n-data-table-expand-trigger),
:deep(.n-data-table-td--expand .n-data-table-expand-trigger) {
    display: none;
}
</style>
