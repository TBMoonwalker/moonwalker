<template>
    <n-data-table
        size="small"
        remote
        ref="table"
        :columns="columns_open_trades"
        :data="displayed_open_trades || []"
        :loading="isTableLoading"
        :row-class-name="row_classes"
        :render-expand-icon="renderExpandIcon"
        :locale="{ emptyText: tableEmptyText }"
        aria-label="Open trades table"
        @update:sorter="handleSorterChange"
    />
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { NDataTable } from 'naive-ui/es/data-table'
import { useDialog } from 'naive-ui/es/dialog'
import { useMessage } from 'naive-ui/es/message'
import { useWebSocketDataStore } from '../stores/websocket'
import { useTradesStore } from '../stores/trades'
import { storeToRefs } from 'pinia'
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
const { configuredMinTimeframe, loadConfiguredMinTimeframe } =
    useConfiguredMinTimeframe()
const sortState = ref<TradeTableSortState | null>(null)

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
const {
    handleAddManualBuy,
    handleDealBuy,
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
    renderExpandIcon,
    rowClasses: row_classes,
} = useOpenTradeColumns({
    configuredMinTimeframe,
    globalTradingPaused: computed(() => Boolean(props.globalTradingPaused)),
    isMobile,
    isMissionActionLoading,
    isTablet,
    missionActionErrors,
    onAddManualBuy: handleAddManualBuy,
    onDealBuy: handleDealBuy,
    onDealSell: handleDealSell,
    onDealStop: handleDealStop,
    onPauseMission: (rowData) => handlePauseMission(rowData.symbol),
    onResumeMission: (rowData) => handleResumeMission(rowData.symbol),
    sortState,
})

function handleSorterChange(sorter: unknown): void {
    sortState.value = resolveTradeTableSortState(sorter)
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

:deep(.n-data-table-expand-trigger) {
    height: 16px;
}

:deep(.trade-expand-button) {
    min-width: 28px;
    min-height: 28px;
    padding: 0;
}
</style>
