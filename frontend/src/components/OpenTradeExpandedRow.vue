<template>
    <n-flex justify="space-around">
        <n-card>
            <n-timeline :horizontal="false">
                <n-timeline-item
                    title="Base order"
                    :content="baseOrderContent"
                    type="info"
                    :time="baseOrderTime"
                />
                <n-timeline-item
                    v-for="(order, index) in safetyOrders"
                    :key="order.id ?? index"
                    :title="`Safety order ${index + 1}`"
                    :content="getSafetyOrderContent(order)"
                    type="success"
                    :time="formatTimestamp(order.timestamp)"
                />
            </n-timeline>
            <div class="manual-order-actions">
                <n-button
                    tertiary
                    size="small"
                    type="primary"
                    @click="emitAddOrderManually"
                >
                    Add order manually
                </n-button>
            </div>
        </n-card>
        <TradeReplayChart
            :symbol="props.rowData.symbol"
            :precision="Number(props.rowData.precision ?? 0)"
            :start-timestamp="props.rowData.baseorder.timestamp"
            :min-timeframe="props.minTimeframe"
            :markers="chartMarkers"
            :price-lines="chartPriceLines"
        />
    </n-flex>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { NButton } from 'naive-ui/es/button'

import TradeReplayChart from './TradeReplayChart.vue'
import { formatTradingViewDate } from '../helpers/date'
import type { TimeframeChoice } from '../helpers/openTrades'

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

const BUY_MARKER_COLOR = '#1D5C49'
const BUY_LINE_COLOR = '#1D5C49'
const TP_LINE_COLOR = '#B78A2E'

const safetyOrders = computed(() =>
    Array.isArray(props.rowData.safetyorder) ? props.rowData.safetyorder : [],
)

const baseOrderTime = computed(() => formatTimestamp(props.rowData.baseorder.timestamp))
const baseOrderContent = computed(
    () =>
        `Order size: ${formatQuoteAmount(props.rowData.baseorder.ordersize)} | Amount: ${formatAssetAmount(props.rowData.baseorder.amount)} | Price: ${formatPrice(props.rowData.baseorder.price)}`,
)

const chartMarkers = computed(() => [
    {
        timestamp: props.rowData.baseorder.timestamp,
        position: 'belowBar' as const,
        color: BUY_MARKER_COLOR,
        shape: 'arrowUp' as const,
        text: 'Buy',
    },
    ...safetyOrders.value.map((order) => ({
        timestamp: order.timestamp,
        position: 'belowBar' as const,
        color: BUY_MARKER_COLOR,
        shape: 'arrowUp' as const,
        text: 'Buy',
    })),
])

const chartPriceLines = computed(() => [
    {
        price: Number(props.rowData.tp_price),
        color: TP_LINE_COLOR,
        lineStyle: 0 as const,
        title: 'TP',
    },
    {
        price: Number(props.rowData.baseorder.price),
        color: BUY_LINE_COLOR,
        lineStyle: 2 as const,
        title: 'BO',
    },
    ...safetyOrders.value.map((order, index) => ({
        price: Number(order.price),
        color: BUY_LINE_COLOR,
        lineStyle: 2 as const,
        title: `SO${index + 1}`,
    })),
])

function formatTimestamp(timestamp: string | number): string {
    const parsed = Number(timestamp)
    if (!Number.isFinite(parsed)) {
        return ''
    }
    return formatTradingViewDate(Math.trunc(parsed))
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

</script>

<style scoped>
.manual-order-actions {
    display: flex;
    justify-content: flex-end;
    margin-top: 10px;
}
</style>
