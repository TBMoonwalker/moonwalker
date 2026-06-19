<template>
    <n-flex class="expanded-trade-layout">
        <n-card class="expanded-order-card">
            <n-timeline :horizontal="false">
                <n-timeline-item
                    v-for="item in timelineItems"
                    :key="item.key"
                    :title="item.title"
                    :content="item.content"
                    :type="item.type"
                    :time="formatTimestamp(item.timestamp)"
                />
            </n-timeline>
            <div class="manual-order-actions">
                <n-button
                    class="manual-order-button"
                    secondary
                    size="small"
                    type="primary"
                    @click="emitAddOrderManually"
                >
                    Add order manually
                </n-button>
            </div>
        </n-card>
        <TradeReplayChart
            v-if="chartReady"
            class="expanded-replay-chart"
            :symbol="props.rowData.symbol"
            :precision="Number(props.rowData.precision ?? 0)"
            :start-timestamp="replayStartTimestamp"
            :deal-id="props.rowData.deal_id"
            :min-timeframe="props.minTimeframe"
            :markers="chartMarkers"
            :price-lines="chartPriceLines"
        />
    </n-flex>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { NButton } from 'naive-ui/es/button'

import { fetchJson } from '../api/client'
import TradeReplayChart from './TradeReplayChart.vue'
import { formatTradingViewDate } from '../helpers/date'
import type { TimeframeChoice } from '../helpers/openTrades'
import type { TradeExecutionRow } from '../stores/trades'

type OrderData = {
    id: number
    timestamp: string
    ordersize: number
    amount: number
    symbol: string
    price: number
    so_percentage?: number
}

type RowData = {
    symbol: string
    deal_id?: string | null
    lifecycle_mode?: string | null
    sidestep_count?: number
    campaign_started_at?: string | null
    tp_price: number
    precision: number
    current_price?: number
    baseorder: OrderData
    safetyorder?: OrderData[]
}

const props = defineProps<{
    rowData: RowData
    minTimeframe: TimeframeChoice
    onAddOrderManually?: (rowData: RowData) => void
}>()

const BUY_MARKER_COLOR = '#2E7D5B'
const BUY_LINE_COLOR = '#1D5C49'
const SELL_MARKER_COLOR = '#B4443F'
const TP_LINE_COLOR = '#B78A2E'

type TimelineItem = {
    key: string
    title: string
    content: string
    type: 'info' | 'success' | 'warning'
    timestamp: string | number
}

const executions = ref<TradeExecutionRow[]>([])

const safetyOrders = computed(() =>
    Array.isArray(props.rowData.safetyorder) ? props.rowData.safetyorder : [],
)
const isSidestepLifecycle = computed(
    () => String(props.rowData.lifecycle_mode ?? '') === 'sidestep_reentry',
)
const requiresExecutionHistory = computed(
    () => isSidestepLifecycle.value && Boolean(props.rowData.deal_id),
)
const executionHistoryResolved = ref(!requiresExecutionHistory.value)
const hasReentered = computed(
    () =>
        isSidestepLifecycle.value &&
        Number(props.rowData.sidestep_count ?? 0) > 0,
)
const sortedExecutions = computed(() =>
    [...executions.value].sort(
        (left, right) => Number(left.timestamp) - Number(right.timestamp),
    ),
)
const useExecutionHistory = computed(
    () => isSidestepLifecycle.value && sortedExecutions.value.length > 0,
)
const chartReady = computed(
    () => !requiresExecutionHistory.value || executionHistoryResolved.value,
)
const replayStartTimestamp = computed(() =>
    useExecutionHistory.value
        ? sortedExecutions.value[0]?.timestamp ?? props.rowData.baseorder.timestamp
        : hasReentered.value && props.rowData.campaign_started_at
        ? props.rowData.campaign_started_at
        : props.rowData.baseorder.timestamp,
)
const timelineItems = computed<TimelineItem[]>(() => {
    if (!useExecutionHistory.value) {
        return [
            {
                key: `base-${props.rowData.baseorder.id ?? 0}`,
                title: hasReentered.value ? 'Re-entry buy' : 'Base order',
                content: `Order size: ${formatQuoteAmount(props.rowData.baseorder.ordersize)} | Amount: ${formatAssetAmount(props.rowData.baseorder.amount)} | Price: ${formatPrice(props.rowData.baseorder.price)}`,
                type: 'info',
                timestamp: props.rowData.baseorder.timestamp,
            },
            ...safetyOrders.value.map((order, index) => ({
                key: String(order.id ?? index),
                title: `Safety order ${index + 1}`,
                content: getSafetyOrderContent(order),
                type: 'success' as const,
                timestamp: order.timestamp,
            })),
        ]
    }

    return sortedExecutions.value.map((execution, index) => {
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
        return {
            key: `${execution.id ?? index}-${execution.role}-${execution.timestamp}`,
            title: isBuy
                ? getBuyTitle(execution, buyIndex, baseOrderIndex)
                : getSellTitle(execution, sellIndex),
            content: [
                `Order size: ${formatQuoteAmount(execution.ordersize)}`,
                `Amount: ${formatAssetAmount(execution.amount)}`,
                `Price: ${formatPrice(execution.price)}`,
                ...(isBuy &&
                execution.so_percentage !== null &&
                execution.so_percentage !== undefined
                    ? [`Percentage: ${formatPercent(execution.so_percentage)}`]
                    : []),
            ].join(' | '),
            type: isBuy
                ? execution.role === 'base_order'
                    ? 'info'
                    : 'success'
                : 'warning',
            timestamp: execution.timestamp,
        }
    })
})

const chartMarkers = computed(() => {
    if (!useExecutionHistory.value) {
        return [
            {
                timestamp: props.rowData.baseorder.timestamp,
                position: 'belowBar' as const,
                color: BUY_MARKER_COLOR,
                shape: 'arrowUp' as const,
                text: hasReentered.value ? 'Re-entry' : 'Buy',
            },
            ...safetyOrders.value.map((order) => ({
                timestamp: order.timestamp,
                position: 'belowBar' as const,
                color: BUY_MARKER_COLOR,
                shape: 'arrowUp' as const,
                text: 'Buy',
            })),
        ]
    }

    return sortedExecutions.value.map((execution, index) => {
        if (execution.side === 'buy') {
            const baseOrderIndex = countExecutionsUntil(
                sortedExecutions.value,
                index,
                (candidate) =>
                    candidate.side === 'buy' && candidate.role === 'base_order',
            )
            return {
                timestamp: execution.timestamp,
                position: 'belowBar' as const,
                color: BUY_MARKER_COLOR,
                shape: 'arrowUp' as const,
                text:
                    execution.role === 'base_order' && baseOrderIndex > 1
                        ? 'Re-entry'
                        : 'Buy',
            }
        }

        const sellPrice = Number(execution.price)
        const hasExactSellPrice = Number.isFinite(sellPrice) && sellPrice > 0
        return {
            timestamp: execution.timestamp,
            position: hasExactSellPrice
                ? ('atPriceMiddle' as const)
                : ('aboveBar' as const),
            ...(hasExactSellPrice
                ? { price: sellPrice }
                : {}),
            color: SELL_MARKER_COLOR,
            shape: 'arrowDown' as const,
            text: 'Exit',
        }
    })
})

const chartPriceLines = computed(() => {
    const lines: Array<{
        price: number
        color: string
        lineStyle: 0 | 1 | 2 | 3 | 4
        title: string
    }> = [
        {
            price: Number(props.rowData.tp_price),
            color: TP_LINE_COLOR,
            lineStyle: 0 as const,
            title: 'TP',
        },
    ]

    if (!useExecutionHistory.value) {
        lines.push({
            price: Number(props.rowData.baseorder.price),
            color: BUY_LINE_COLOR,
            lineStyle: 2 as const,
            title: 'BO',
        })
        safetyOrders.value.forEach((order, index) => {
            lines.push({
                price: Number(order.price),
                color: BUY_LINE_COLOR,
                lineStyle: 2 as const,
                title: `SO${index + 1}`,
            })
        })
        return lines
    }

    sortedExecutions.value.forEach((execution, index) => {
        const price = Number(execution.price)
        if (!Number.isFinite(price) || price <= 0) {
            return
        }
        if (execution.side === 'buy') {
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
            lines.push({
                price,
                color: BUY_LINE_COLOR,
                lineStyle: 2 as const,
                title: getBuyLineTitle(execution, buyIndex, baseOrderIndex),
            })
            return
        }
        lines.push({
            price,
            color: SELL_MARKER_COLOR,
            lineStyle: 3 as const,
            title: `EXIT${countExecutionsUntil(
                sortedExecutions.value,
                index,
                (candidate) => candidate.side === 'sell',
            )}`,
        })
    })
    return lines
})

function formatTimestamp(timestamp: string | number): string {
    const parsed = Number(timestamp)
    if (!Number.isFinite(parsed)) {
        return ''
    }
    return formatTradingViewDate(Math.trunc(parsed))
}

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
        return baseOrderIndex <= 1
            ? 'Base order'
            : `Re-entry buy ${baseOrderIndex - 1}`
    }
    const orderCount = Number(execution.order_count)
    if (Number.isFinite(orderCount) && orderCount > 0) {
        return `Safety order ${orderCount}`
    }
    return `Safety order ${Math.max(1, buyIndex - 1)}`
}

function getSellTitle(execution: TradeExecutionRow, sellIndex: number): string {
    if (execution.role === 'partial_sell') {
        return 'Partial sell'
    }
    return `Sidestep exit ${sellIndex}`
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

function getSafetyOrderContent(order: OrderData): string {
    return `Order size: ${formatQuoteAmount(order.ordersize)} | Amount: ${formatAssetAmount(order.amount)} | Price: ${formatPrice(order.price)} | Percentage: ${formatPercent(order.so_percentage)}`
}

function toNumberOrZero(value: unknown): number {
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : 0
}

function formatQuoteAmount(value: unknown): string {
    return toNumberOrZero(value).toFixed(2)
}

function formatAssetAmount(value: unknown): string {
    return toNumberOrZero(value).toFixed(8).replace(/\.?0+$/, '')
}

function formatPrice(value: unknown): string {
    const decimals = Math.max(0, Number(props.rowData.precision ?? 0))
    return toNumberOrZero(value).toFixed(decimals)
}

function formatPercent(value: unknown): string {
    return `${toNumberOrZero(value).toFixed(2)} %`
}

function emitAddOrderManually(): void {
    if (typeof props.onAddOrderManually === 'function') {
        props.onAddOrderManually(props.rowData)
    }
}

async function loadExecutions(): Promise<void> {
    if (!requiresExecutionHistory.value) {
        executionHistoryResolved.value = true
        return
    }
    try {
        const response = await fetchJson<{ result: TradeExecutionRow[] }>(
            `/trades/executions/${props.rowData.deal_id}`,
        )
        executions.value = Array.isArray(response.result) ? response.result : []
    } catch (_error) {
        executions.value = []
    } finally {
        executionHistoryResolved.value = true
    }
}

onMounted(() => {
    void loadExecutions()
})

</script>

<style scoped>
.expanded-trade-layout {
    align-items: stretch;
    gap: 16px;
    width: 100%;
}

.expanded-order-card {
    flex: 0 1 340px;
    min-width: 280px;
}

.expanded-replay-chart {
    flex: 1 1 520px;
    min-width: 0;
}

.manual-order-actions {
    display: flex;
    justify-content: flex-end;
    margin-top: 10px;
}

.manual-order-actions :deep(.manual-order-button) {
    --n-color: var(--mw-color-primary-soft) !important;
    --n-color-hover: color-mix(
        in srgb,
        var(--mw-color-primary-soft) 84%,
        var(--mw-color-text-primary)
    ) !important;
    --n-color-pressed: color-mix(
        in srgb,
        var(--mw-color-primary-soft) 74%,
        var(--mw-color-text-primary)
    ) !important;
    --n-border: 1px solid var(--mw-color-border-strong) !important;
    --n-border-hover: 1px solid var(--mw-color-primary) !important;
    --n-border-pressed: 1px solid var(--mw-color-primary-strong) !important;
    --n-text-color: var(--mw-color-text-primary) !important;
    --n-text-color-hover: var(--mw-color-text-primary) !important;
    --n-text-color-pressed: var(--mw-color-text-primary) !important;
    font-weight: 450;
}

@media (max-width: 900px) {
    .expanded-order-card,
    .expanded-replay-chart {
        flex-basis: 100%;
    }
}
</style>
