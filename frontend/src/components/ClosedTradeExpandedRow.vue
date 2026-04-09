<template>
    <n-flex class="closed-trade-replay-shell">
        <n-card class="closed-trade-timeline-card">
            <n-alert
                v-if="showPartialReplayNotice"
                type="warning"
                :bordered="false"
                class="replay-notice"
            >
                Partial replay: buy markers are available, but older partial sells before
                the ledger backfill may be missing.
            </n-alert>
            <n-alert
                v-if="loadError"
                type="error"
                :bordered="false"
                class="replay-notice"
            >
                {{ loadError }}
            </n-alert>
            <n-timeline v-if="timelineItems.length > 0" :horizontal="false">
                <n-timeline-item
                    v-for="item in timelineItems"
                    :key="item.key"
                    :title="item.title"
                    :content="item.content"
                    :type="item.type"
                    :time="formatTimestamp(item.timestamp)"
                />
            </n-timeline>
            <n-text v-else depth="3">
                {{ timelineEmptyText }}
            </n-text>
        </n-card>

        <TradeReplayChart
            v-if="canRenderChart"
            :symbol="props.rowData.symbol"
            :precision="chartPrecision"
            :start-timestamp="startTimestamp"
            :end-timestamp="endTimestamp"
            :archive-deal-id="props.rowData.deal_id"
            :min-timeframe="props.minTimeframe"
            :markers="chartMarkers"
            :price-lines="chartPriceLines"
        />
    </n-flex>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { fetchJson } from '../api/client'
import { formatTradingViewDate } from '../helpers/date'
import type { TimeframeChoice } from '../helpers/openTrades'
import type { ClosedTradeRow, TradeExecutionRow } from '../stores/trades'
import TradeReplayChart from './TradeReplayChart.vue'

const BUY_MARKER_COLOR = 'rgb(99, 226, 183)'
const BUY_LINE_COLOR = '#1D5C49'
const SELL_PROFIT_COLOR = 'rgb(99, 226, 183)'
const SELL_LOSS_COLOR = 'rgb(224, 108, 117)'

type TimelineItem = {
    key: string
    title: string
    content: string
    type: 'info' | 'success' | 'error' | 'warning'
    timestamp: string | number
}

const props = defineProps<{
    rowData: ClosedTradeRow
    minTimeframe: TimeframeChoice
}>()

const executions = ref<TradeExecutionRow[]>([])
const loadError = ref('')
const isLoading = ref(false)

const sortedExecutions = computed(() =>
    [...executions.value].sort(
        (left, right) => Number(left.timestamp) - Number(right.timestamp),
    ),
)

const buyExecutions = computed(() =>
    sortedExecutions.value.filter((execution) => execution.side === 'buy'),
)

const finalSellExecution = computed(() => {
    const sells = sortedExecutions.value.filter(
        (execution) => execution.side === 'sell',
    )
    return sells.length > 0 ? sells[sells.length - 1] : null
})

const showPartialReplayNotice = computed(
    () => Boolean(props.rowData.deal_id) && !props.rowData.execution_history_complete,
)

const startTimestamp = computed(
    () => buyExecutions.value[0]?.timestamp ?? props.rowData.open_date,
)

const endTimestamp = computed(
    () => finalSellExecution.value?.timestamp ?? props.rowData.close_date,
)

const chartPrecision = computed(() => Number(props.rowData.precision ?? 2))

const canRenderChart = computed(
    () => !loadError.value && buyExecutions.value.length > 0,
)

const sellColor = computed(() =>
    Number(props.rowData.profit_percent) >= 0
        ? SELL_PROFIT_COLOR
        : SELL_LOSS_COLOR,
)

const timelineEmptyText = computed(() => {
    if (isLoading.value) {
        return 'Loading execution replay...'
    }
    if (!props.rowData.deal_id) {
        return 'Legacy closed trade without execution history.'
    }
    return 'No execution replay rows available.'
})

const timelineItems = computed<TimelineItem[]>(() =>
    sortedExecutions.value.map((execution, index) => {
        const isBuy = execution.side === 'buy'
        const title = isBuy
            ? getBuyTitle(execution, index)
            : execution.role === 'final_sell'
              ? 'Final sell'
              : 'Partial sell'
        const content = [
            `Order size: ${formatQuoteAmount(execution.ordersize)}`,
            `Amount: ${formatAssetAmount(execution.amount)}`,
            `Price: ${formatPrice(execution.price)}`,
        ]
        if (isBuy && execution.so_percentage !== null && execution.so_percentage !== undefined) {
            content.push(`Percentage: ${formatPercent(execution.so_percentage)}`)
        }
        return {
            key: `${execution.id ?? index}-${execution.role}-${execution.timestamp}`,
            title,
            content: content.join(' | '),
            type: isBuy
                ? execution.role === 'base_order'
                    ? 'info'
                    : 'success'
                : Number(props.rowData.profit_percent) >= 0
                  ? 'success'
                  : 'error',
            timestamp: execution.timestamp,
        }
    }),
)

const chartMarkers = computed(() => {
    const markers = buyExecutions.value.map((execution) => ({
        timestamp: execution.timestamp,
        position: 'belowBar' as const,
        color: BUY_MARKER_COLOR,
        shape: 'arrowUp' as const,
        text: 'Buy',
    }))
    if (finalSellExecution.value) {
        const finalSellPrice = Number(finalSellExecution.value.price)
        const hasExactFinalSellPrice =
            Number.isFinite(finalSellPrice) && finalSellPrice > 0
        markers.push({
            timestamp: finalSellExecution.value.timestamp,
            position: hasExactFinalSellPrice
                ? ('atPriceMiddle' as const)
                : ('aboveBar' as const),
            ...(hasExactFinalSellPrice
                ? { price: finalSellPrice }
                : {}),
            color: sellColor.value,
            shape: 'arrowDown' as const,
            text: 'Sell',
        })
    }
    return markers
})

const chartPriceLines = computed(() => {
    const lines = buyExecutions.value.map((execution, index) => ({
        price: Number(execution.price),
        color: BUY_LINE_COLOR,
        lineStyle: 2 as const,
        title: execution.role === 'base_order' ? 'BO' : `SO${index}`,
    }))
    if (finalSellExecution.value) {
        const finalSellPrice = Number(finalSellExecution.value.price)
        if (Number.isFinite(finalSellPrice) && finalSellPrice > 0) {
            lines.push({
                price: finalSellPrice,
                color: sellColor.value,
                lineStyle: 3 as const,
                title: 'SELL',
            })
        }
    }
    return lines
})

function getBuyTitle(execution: TradeExecutionRow, index: number): string {
    if (execution.role === 'base_order' || index === 0) {
        return 'Base order'
    }
    const orderCount = Number(execution.order_count)
    if (Number.isFinite(orderCount) && orderCount > 0) {
        return `Safety order ${orderCount}`
    }
    return `Safety order ${index}`
}

function toNumberOrZero(value: unknown): number {
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : 0
}

function formatTimestamp(timestamp: string | number): string {
    const parsed = Number(timestamp)
    if (!Number.isFinite(parsed)) {
        return ''
    }
    return formatTradingViewDate(Math.trunc(parsed))
}

function formatQuoteAmount(value: unknown): string {
    return toNumberOrZero(value).toFixed(2)
}

function formatAssetAmount(value: unknown): string {
    return toNumberOrZero(value).toFixed(8).replace(/\.?0+$/, '')
}

function formatPrice(value: unknown): string {
    const decimals = Math.max(0, Number(props.rowData.precision ?? 2))
    return toNumberOrZero(value).toFixed(decimals).replace(/\.?0+$/, '')
}

function formatPercent(value: unknown): string {
    return `${toNumberOrZero(value).toFixed(2)} %`
}

async function loadExecutions(): Promise<void> {
    if (!props.rowData.deal_id) {
        return
    }
    isLoading.value = true
    loadError.value = ''
    try {
        const response = await fetchJson<{ result: TradeExecutionRow[] }>(
            `/trades/executions/${props.rowData.deal_id}`,
        )
        executions.value = Array.isArray(response.result) ? response.result : []
    } catch (error) {
        loadError.value = error instanceof Error
            ? error.message
            : 'Failed loading execution replay.'
        executions.value = []
    } finally {
        isLoading.value = false
    }
}

onMounted(() => {
    void loadExecutions()
})
</script>

<style scoped>
.closed-trade-replay-shell {
    gap: 16px;
    align-items: stretch;
}

.closed-trade-timeline-card {
    flex: 0 0 340px;
    max-width: 360px;
}

.replay-notice {
    margin-bottom: 12px;
}

@media (max-width: 1023px) {
    .closed-trade-replay-shell {
        flex-direction: column;
    }

    .closed-trade-timeline-card {
        flex-basis: auto;
        max-width: none;
        width: 100%;
    }
}
</style>
