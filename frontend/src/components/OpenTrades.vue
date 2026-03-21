<template>
    <n-data-table
        size="small"
        remote
        ref="table"
        :columns="columns_open_trades"
        :data="open_trades || []"
        :loading="isTableLoading"
        :row-class-name="row_classes"
        :render-expand-icon="renderExpandIcon"
        :locale="{ emptyText: tableEmptyText }"
        aria-label="Open trades table"
    />
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { NDataTable } from 'naive-ui/es/data-table'
import { useDialog } from 'naive-ui/es/dialog'
import { useMessage } from 'naive-ui/es/message'
import { useWebSocketDataStore } from '../stores/websocket'
import { useTradesStore } from '../stores/trades'
import { storeToRefs } from 'pinia'
import { useConfiguredMinTimeframe } from '../composables/useConfiguredMinTimeframe'
import { useOpenTradeActions } from '../composables/useOpenTradeActions'
import { useOpenTradeColumns } from '../composables/useOpenTradeColumns'
import { useTradeTableFeed } from '../composables/useTradeTableFeed'
import { useViewport } from '../composables/useViewport'
import {
    toFiniteNonNegative,
    type OpenTradeRow,
} from '../helpers/openTrades'

const statistics_store = useWebSocketDataStore("statistics")
const statistics_data = storeToRefs(statistics_store)
const trades_store = useTradesStore()

const dialog = useDialog()
const message = useMessage()

const { isMobile, isTablet } = useViewport()
const { configuredMinTimeframe, loadConfiguredMinTimeframe } =
    useConfiguredMinTimeframe()

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
    columnsOpenTrades: columns_open_trades,
    renderExpandIcon,
    rowClasses: row_classes,
} = useOpenTradeColumns({
    configuredMinTimeframe,
    isMobile,
    isTablet,
    onAddManualBuy: handleAddManualBuy,
    onDealBuy: handleDealBuy,
    onDealSell: handleDealSell,
    onDealStop: handleDealStop,
})

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
