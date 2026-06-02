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
            <n-alert
                v-if="missionSummaryText"
                type="info"
                :bordered="false"
                class="replay-notice"
            >
                {{ missionSummaryText }}
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

        <div v-if="canRenderChart" class="closed-trade-chart-panel">
            <TradeReplayChart
                :symbol="props.rowData.symbol"
                :precision="chartPrecision"
                :start-timestamp="startTimestamp"
                :end-timestamp="endTimestamp"
                :archive-deal-id="props.rowData.deal_id"
                :min-timeframe="props.minTimeframe"
                :markers="chartMarkers"
                :price-lines="chartPriceLines"
            />
        </div>
    </n-flex>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { fetchJson } from '../api/client'
import { formatTradingViewDate } from '../helpers/date'
import type { TimeframeChoice } from '../helpers/openTrades'
import type { ClosedTradeRow, TradeExecutionRow } from '../stores/trades'
import TradeReplayChart from './TradeReplayChart.vue'

const BUY_MARKER_COLOR = '#2E7D5B'
const BUY_LINE_COLOR = '#1D5C49'
const SELL_PROFIT_COLOR = '#2E7D5B'
const SELL_LOSS_COLOR = '#B4443F'

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

const sellExecutions = computed(() =>
    sortedExecutions.value.filter((execution) => execution.side === 'sell'),
)

const finalSellExecution = computed(() => {
    const sells = sellExecutions.value
    return sells.length > 0 ? sells[sells.length - 1] : null
})

const showPartialReplayNotice = computed(
    () => Boolean(props.rowData.deal_id) && !props.rowData.execution_history_complete,
)

const sidestepExitCount = computed(() =>
    Math.max(0, sellExecutions.value.length - 1),
)

const reentryBuyCount = computed(() =>
    Math.max(
        0,
        buyExecutions.value.filter((execution) => execution.role === 'base_order')
            .length - 1,
    ),
)

const missionSummaryText = computed(() => {
    if (sidestepExitCount.value <= 0 && reentryBuyCount.value <= 0) {
        return ''
    }
    return [
        'Campaign summary:',
        `${sidestepExitCount.value} sidestep exit${sidestepExitCount.value === 1 ? '' : 's'}`,
        `${reentryBuyCount.value} re-entry bu${reentryBuyCount.value === 1 ? 'y' : 'ys'}`,
        `Final outcome ${formatPercent(props.rowData.profit_percent)}`,
    ].join(' | ')
})

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
        const buyIndex = countExecutionsUntil(
            sortedExecutions.value,
            index,
            (candidate) => candidate.side === 'buy',
        )
        const baseOrderIndex = countExecutionsUntil(
            sortedExecutions.value,
            index,
            (candidate) =>
                candidate.side === 'buy' && candidate.role === 'base_order',
        )
        const sellIndex = countExecutionsUntil(
            sortedExecutions.value,
            index,
            (candidate) => candidate.side === 'sell',
        )
        const title = isBuy
            ? getBuyTitle(execution, buyIndex, baseOrderIndex)
            : getSellTitle(execution, sellIndex, sellExecutions.value.length)
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
    const markers: Array<{
        timestamp: string | number
        position:
            | 'aboveBar'
            | 'belowBar'
            | 'inBar'
            | 'atPriceTop'
            | 'atPriceBottom'
            | 'atPriceMiddle'
        color: string
        shape: 'arrowUp' | 'arrowDown' | 'circle'
        text: string
        price?: number
    }> = []

    sortedExecutions.value.forEach((execution, index) => {
        if (execution.side === 'buy') {
            const baseOrderIndex = countExecutionsUntil(
                sortedExecutions.value,
                index,
                (candidate) =>
                    candidate.side === 'buy' && candidate.role === 'base_order',
            )
            markers.push({
                timestamp: execution.timestamp,
                position: 'belowBar' as const,
                color: BUY_MARKER_COLOR,
                shape: 'arrowUp' as const,
                text:
                    execution.role === 'base_order' && baseOrderIndex > 1
                        ? 'Re-entry'
                        : 'Buy',
            })
            return
        }

        const sellIndex = countExecutionsUntil(
            sortedExecutions.value,
            index,
            (candidate) => candidate.side === 'sell',
        )
        if (sellIndex >= sellExecutions.value.length) {
            return
        }

        const sellPrice = Number(execution.price)
        const hasExactSellPrice = Number.isFinite(sellPrice) && sellPrice > 0
        markers.push({
            timestamp: execution.timestamp,
            position: hasExactSellPrice
                ? ('atPriceMiddle' as const)
                : ('aboveBar' as const),
            ...(hasExactSellPrice
                ? { price: sellPrice }
                : {}),
            color: sellColor.value,
            shape: 'arrowDown' as const,
            text: 'Exit',
        })
    })

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
    const lines: Array<{
        price: number
        color: string
        lineStyle: 0 | 1 | 2 | 3 | 4
        title: string
    }> = []

    buyExecutions.value.forEach((execution, index) => {
        const price = Number(execution.price)
        if (!Number.isFinite(price) || price <= 0) {
            return
        }
        const buyIndex = countExecutionsUntil(
            buyExecutions.value,
            index,
            () => true,
        )
        const baseOrderIndex = countExecutionsUntil(
            buyExecutions.value,
            index,
            (candidate) => candidate.role === 'base_order',
        )
        lines.push({
            price,
            color: BUY_LINE_COLOR,
            lineStyle: 2 as const,
            title: getBuyLineTitle(execution, buyIndex, baseOrderIndex),
        })
    })

    sellExecutions.value.slice(0, -1).forEach((execution, index) => {
        const sellPrice = Number(execution.price)
        if (Number.isFinite(sellPrice) && sellPrice > 0) {
            lines.push({
                price: sellPrice,
                color: sellColor.value,
                lineStyle: 3 as const,
                title: getSellLineTitle(index + 1, sellExecutions.value.length),
            })
        }
    })
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

function countExecutionsUntil(
    executionsToCount: TradeExecutionRow[],
    endIndex: number,
    matcher: (execution: TradeExecutionRow) => boolean,
): number {
    let count = 0
    for (let index = 0; index <= endIndex; index += 1) {
        if (matcher(executionsToCount[index])) {
            count += 1
        }
    }
    return count
}

function getBuyTitle(
    execution: TradeExecutionRow,
    buyIndex: number,
    baseOrderIndex: number,
): string {
    if (execution.role === 'manual_buy') {
        return 'Manual buy'
    }
    if (execution.role === 'base_order') {
        if (baseOrderIndex <= 1) {
            return 'Base order'
        }
        return `Re-entry buy ${baseOrderIndex - 1}`
    }
    const orderCount = Number(execution.order_count)
    if (Number.isFinite(orderCount) && orderCount > 0) {
        return `Safety order ${orderCount}`
    }
    if (buyIndex <= 1) {
        return 'Base order'
    }
    return `Safety order ${buyIndex - 1}`
}

function getSellTitle(
    execution: TradeExecutionRow,
    sellIndex: number,
    totalSellCount: number,
): string {
    if (execution.role === 'partial_sell') {
        return 'Partial sell'
    }
    if (sellIndex < totalSellCount) {
        return `Sidestep exit ${sellIndex}`
    }
    if (totalSellCount > 1) {
        return 'Final sell'
    }
    return 'Sell'
}

function getBuyLineTitle(
    execution: TradeExecutionRow,
    buyIndex: number,
    baseOrderIndex: number,
): string {
    if (execution.role === 'manual_buy') {
        return 'MANUAL'
    }
    if (execution.role === 'base_order') {
        return baseOrderIndex <= 1 ? 'BO' : `RE${baseOrderIndex - 1}`
    }
    const orderCount = Number(execution.order_count)
    if (Number.isFinite(orderCount) && orderCount > 0) {
        return `SO${orderCount}`
    }
    return `SO${Math.max(1, buyIndex - 1)}`
}

function getSellLineTitle(sellIndex: number, totalSellCount: number): string {
    if (sellIndex < totalSellCount) {
        return `EXIT${sellIndex}`
    }
    return totalSellCount > 1 ? 'SELL' : 'SELL'
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
    flex-wrap: nowrap;
}

.closed-trade-timeline-card {
    flex: 0 0 340px;
    max-width: 360px;
}

.closed-trade-chart-panel {
    flex: 1 1 0;
    min-width: 0;
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

    .closed-trade-chart-panel {
        width: 100%;
    }
}
</style>
