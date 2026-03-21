<template>
    <n-flex justify="space-around">
        <n-card>
            <n-timeline :horizontal="false">
                <n-timeline-item
                    title="Baseorder"
                    :content="baseOrderContent"
                    type="info"
                    :time="baseOrderTime"
                />
                <n-timeline-item
                    v-for="(order, index) in safetyOrders"
                    :key="order.id ?? index"
                    :title="`Safetyorder ${index + 1}`"
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
        <n-card class="expand-chart-card" content-style="padding: 0;">
            <div class="expand-chart-frame">
                <div ref="chartRef" class="expand-chart" />
            </div>
        </n-card>
    </n-flex>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { createChart, CandlestickSeries, createSeriesMarkers } from 'lightweight-charts'
import { NButton } from 'naive-ui/es/button'

import { fetchJson } from '../api/client'
import { formatTradingViewDate } from '../helpers/date'
import { createDecimal } from '../helpers/validators'
import { useOhlcvStore } from '../stores/ohlcv'

type TimeframeChoice = {
    timerange: string
    seconds: number
}

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

const MAX_VISIBLE_CANDLES = 500
const PRE_ROLL_CANDLES = 2
const TIMEFRAME_CHOICES: TimeframeChoice[] = [
    { timerange: "1m", seconds: 60 },
    { timerange: "5min", seconds: 5 * 60 },
    { timerange: "15min", seconds: 15 * 60 },
    { timerange: "30min", seconds: 30 * 60 },
    { timerange: "60min", seconds: 60 * 60 },
    { timerange: "4h", seconds: 4 * 60 * 60 },
    { timerange: "1D", seconds: 24 * 60 * 60 },
]

const chartRef = ref<HTMLElement | null>(null)
const ohlcvStore = useOhlcvStore()
let chart: ReturnType<typeof createChart> | null = null

const safetyOrders = computed(() =>
    Array.isArray(props.rowData.safetyorder) ? props.rowData.safetyorder : [],
)

const baseOrderTime = computed(() => formatTimestamp(props.rowData.baseorder.timestamp))
const baseOrderContent = computed(
    () =>
        `Order size: ${formatQuoteAmount(props.rowData.baseorder.ordersize)} | Amount: ${formatAssetAmount(props.rowData.baseorder.amount)} | Price: ${formatPrice(props.rowData.baseorder.price)}`,
)

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

function selectTimeframe(
    beginTimestamp: string | number,
    minTimeframe: TimeframeChoice,
): TimeframeChoice {
    const beginMs = Number(beginTimestamp)
    const nowMs = Date.now()
    const durationSeconds = Math.max(0, Math.floor((nowMs - beginMs) / 1000))
    const choices = TIMEFRAME_CHOICES.filter(
        (choice) => choice.seconds >= minTimeframe.seconds,
    )

    for (const choice of choices) {
        if (durationSeconds / choice.seconds <= MAX_VISIBLE_CANDLES) {
            return choice
        }
    }

    return choices[choices.length - 1]
}

function getLocalOffsetSeconds(): number {
    return -new Date().getTimezoneOffset() * 60
}

async function initChart(): Promise<void> {
    if (!chartRef.value) {
        return
    }

    const [symbol, currency] = props.rowData.symbol.split("/")
    const beginTimestamp = props.rowData.baseorder.timestamp
    const precision = createDecimal(props.rowData.precision)
    const timeframe = selectTimeframe(beginTimestamp, props.minTimeframe)
    const historyStart = Math.max(
        0,
        Number(beginTimestamp) - timeframe.seconds * PRE_ROLL_CANDLES * 1000,
    )

    chart = createChart(chartRef.value, {
        autoSize: true,
        layout: {
            background: { color: 'rgb(24, 24, 28)' },
            textColor: '#fff',
        },
        grid: {
            vertLines: { visible: false },
            horzLines: { visible: false },
        },
        timeScale: {
            borderVisible: false,
            timeVisible: true,
        },
        rightPriceScale: {
            borderVisible: false,
        },
        handleScroll: true,
        handleScale: false,
    })

    const candlestickSeries = chart.addSeries(CandlestickSeries, {
        upColor: "rgb(99, 226, 183)",
        borderUpColor: "rgb(99, 226, 183)",
        wickUpColor: "rgb(99, 226, 183)",
        downColor: "rgb(224, 108, 117)",
        borderDownColor: "rgb(224, 108, 117)",
        wickDownColor: "rgb(224, 108, 117)",
        priceFormat: {
            type: 'price',
            minMove: precision,
        },
    })

    const cacheKey = `${symbol}-${currency}-${timeframe.timerange}-${historyStart}`
    let tickerData: Array<Record<string, number>> = []

    try {
        tickerData = await fetchJson<Array<Record<string, number>>>(
            `/data/ohlcv/${symbol + "-" + currency.toUpperCase()}/${timeframe.timerange}/${historyStart}/0`,
        )
        ohlcvStore.set(cacheKey, tickerData)
    } catch (_error) {
        tickerData = ohlcvStore.get(cacheKey) ?? []
    }

    const localOffsetSeconds = getLocalOffsetSeconds()
    const localTickerData = tickerData.map((entry) => ({
        ...entry,
        time: Number(entry.time) + localOffsetSeconds,
    }))
    candlestickSeries.setData(localTickerData)

    const markerData: Array<Record<string, number | string>> = []

    candlestickSeries.createPriceLine({
        price: Number(props.rowData.tp_price),
        color: 'orange',
        lineWidth: 2,
        lineStyle: 0,
        axisLabelVisible: true,
        title: 'TP',
    })

    const seconds = timeframe.seconds
    let baseorderDatetime = Math.trunc(Number(beginTimestamp) / 1000)
    baseorderDatetime -= baseorderDatetime % seconds
    baseorderDatetime += localOffsetSeconds

    markerData.push({
        time: baseorderDatetime,
        position: 'belowBar',
        color: '#f68410',
        shape: 'arrowUp',
        text: 'Buy',
    })

    candlestickSeries.createPriceLine({
        price: props.rowData.baseorder.price,
        color: 'green',
        lineWidth: 2,
        lineStyle: 2,
        axisLabelVisible: true,
        title: 'BO',
    })

    for (const [index, order] of safetyOrders.value.entries()) {
        let safetyorderDatetime = Math.trunc(Number(order.timestamp) / 1000)
        safetyorderDatetime -= safetyorderDatetime % seconds
        safetyorderDatetime += localOffsetSeconds

        markerData.push({
            time: safetyorderDatetime,
            position: 'belowBar',
            color: '#f68410',
            shape: 'arrowUp',
            text: 'Buy',
        })

        candlestickSeries.createPriceLine({
            price: order.price,
            color: 'green',
            lineWidth: 2,
            lineStyle: 2,
            axisLabelVisible: true,
            title: `SO${index + 1}`,
        })
    }

    createSeriesMarkers(candlestickSeries, markerData)
    chart.timeScale().fitContent()
}

onMounted(() => {
    void initChart()
})

onUnmounted(() => {
    if (chart) {
        chart.remove()
        chart = null
    }
})
</script>

<style scoped>
.expand-chart-card {
    overflow: hidden;
}

.expand-chart-frame {
    overflow: hidden;
    border-radius: inherit;
}

.expand-chart {
    height: 400px;
    width: 100%;
}

.manual-order-actions {
    display: flex;
    justify-content: flex-end;
    margin-top: 10px;
}
</style>
