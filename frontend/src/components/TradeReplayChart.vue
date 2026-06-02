<template>
    <n-card class="expand-chart-card" content-style="padding: 0;">
        <div class="expand-chart-frame">
            <div v-if="loadError" class="expand-chart-empty">
                {{ loadError }}
            </div>
            <div v-else-if="isEmpty" class="expand-chart-empty">
                No candle data available for this replay window.
            </div>
            <div v-else-if="isLoading && !chartReady" class="expand-chart-empty">
                Loading chart...
            </div>
            <div v-show="chartReady" ref="chartRef" class="expand-chart" />
        </div>
    </n-card>
</template>

<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref } from 'vue'
import {
    CandlestickSeries,
    LineSeries,
    createChart,
    createSeriesMarkers,
} from 'lightweight-charts'

import { fetchJson } from '../api/client'
import { createDecimal } from '../helpers/validators'
import {
    TIMEFRAME_CHOICES,
    splitTradeSymbol,
    type TimeframeChoice,
} from '../helpers/openTrades'
import { useOhlcvStore } from '../stores/ohlcv'

type TradeReplayMarker = {
    timestamp: number | string
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
    price?: number | string | null
}

type NormalizedTradeReplayMarker = {
    time: number
    position: TradeReplayMarker['position']
    color: string
    shape: TradeReplayMarker['shape']
    text: string
}

type ExactTradeReplayMarker = NormalizedTradeReplayMarker & {
    position: 'inBar'
    price: number
}

type TradeReplayPriceLine = {
    price: number | string
    color: string
    lineStyle: 0 | 1 | 2 | 3 | 4
    title: string
}

const props = defineProps<{
    symbol: string
    precision: number
    startTimestamp: number | string
    endTimestamp?: number | string | null
    archiveDealId?: string | null
    minTimeframe: TimeframeChoice
    markers: TradeReplayMarker[]
    priceLines: TradeReplayPriceLine[]
}>()

const MAX_VISIBLE_CANDLES = 500
const PRE_ROLL_CANDLES = 2
const POST_ROLL_CANDLES = 4
const MAX_PRICE_FORMAT_PRECISION = 8

const chartRef = ref<HTMLElement | null>(null)
const isLoading = ref(true)
const isEmpty = ref(false)
const loadError = ref('')
const chartReady = ref(false)
const ohlcvStore = useOhlcvStore()
let chart: ReturnType<typeof createChart> | null = null

function toFiniteNumber(value: number | string | null | undefined): number | null {
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : null
}

function toTimestampMs(value: number | string | null | undefined): number | null {
    if (value === null || value === undefined) {
        return null
    }
    const numeric = Number(value)
    if (Number.isFinite(numeric)) {
        return numeric
    }
    const parsed = Date.parse(String(value))
    return Number.isFinite(parsed) ? parsed : null
}

function normalizeCandleRows(payload: unknown): Array<Record<string, number>> {
    return Array.isArray(payload) ? payload : []
}

function normalizePriceFormatPrecision(value: number): number {
    const normalized = Math.trunc(Number(value))
    if (!Number.isFinite(normalized) || normalized < 0) {
        return 2
    }
    return Math.min(normalized, MAX_PRICE_FORMAT_PRECISION)
}

function nextAnimationFrame(): Promise<void> {
    return new Promise((resolve) => {
        requestAnimationFrame(() => resolve())
    })
}

function selectTimeframe(): TimeframeChoice {
    const beginMs = toFiniteNumber(props.startTimestamp) ?? Date.now()
    const endMs = toFiniteNumber(props.endTimestamp) ?? Date.now()
    const durationSeconds = Math.max(0, Math.floor((endMs - beginMs) / 1000))
    const choices = TIMEFRAME_CHOICES.filter(
        (choice) => choice.seconds >= props.minTimeframe.seconds,
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

function normalizeMarkerTime(
    timestamp: number | string,
    seconds: number,
    localOffsetSeconds: number,
): number | null {
    const timestampMs = toTimestampMs(timestamp)
    if (timestampMs === null) {
        return null
    }
    let normalized = Math.trunc(timestampMs / 1000)
    if (!Number.isFinite(normalized)) {
        return null
    }
    normalized -= normalized % seconds
    normalized += localOffsetSeconds
    return normalized
}

function normalizeExactMarkerTime(
    timestamp: number | string,
    localOffsetSeconds: number,
): number | null {
    const timestampMs = toTimestampMs(timestamp)
    if (timestampMs === null) {
        return null
    }
    const normalized = Math.trunc(timestampMs / 1000)
    if (!Number.isFinite(normalized)) {
        return null
    }
    return normalized + localOffsetSeconds
}

async function initChart(): Promise<void> {
    isLoading.value = true
    isEmpty.value = false
    loadError.value = ''
    chartReady.value = false

    const beginTimestamp = toTimestampMs(props.startTimestamp)
    if (beginTimestamp === null) {
        isEmpty.value = true
        isLoading.value = false
        return
    }

    const endTimestamp = toTimestampMs(props.endTimestamp)
    const [symbol, currency] = splitTradeSymbol(props.symbol)
    const precision = createDecimal(normalizePriceFormatPrecision(props.precision))
    const timeframe = selectTimeframe()
    const historyStart = Math.max(
        0,
        beginTimestamp - timeframe.seconds * PRE_ROLL_CANDLES * 1000,
    )
    const historyEnd =
        endTimestamp === null
            ? null
            : endTimestamp + timeframe.seconds * POST_ROLL_CANDLES * 1000

    const pairSymbol = `${symbol}-${currency.toUpperCase()}`
    const fallbackCacheKey = [
        pairSymbol,
        timeframe.timerange,
        historyStart,
        historyEnd ?? 'live',
    ].join('-')
    const archiveCacheKey = props.archiveDealId
        ? [
            'replay',
            props.archiveDealId,
            timeframe.timerange,
            historyStart,
            historyEnd ?? 'live',
        ].join('-')
        : null
    const historyUrl =
        historyEnd === null
            ? `/data/ohlcv/${pairSymbol}/${timeframe.timerange}/${historyStart}/0`
            : `/data/ohlcv/${pairSymbol}/${timeframe.timerange}/${historyStart}/${historyEnd}/0`
    const archiveUrl = props.archiveDealId
        ? historyEnd === null
            ? `/data/ohlcv/replay/${props.archiveDealId}/${timeframe.timerange}/0`
            : `/data/ohlcv/replay/${props.archiveDealId}/${timeframe.timerange}/${historyStart}/${historyEnd}/0`
        : null

    let tickerData: Array<Record<string, number>> = []
    try {
        if (archiveUrl && archiveCacheKey) {
            try {
                tickerData = normalizeCandleRows(await fetchJson<unknown>(archiveUrl))
                if (tickerData.length > 0) {
                    ohlcvStore.set(archiveCacheKey, tickerData)
                }
            } catch (_error) {
                tickerData = normalizeCandleRows(ohlcvStore.get(archiveCacheKey) ?? [])
            }
        }

        if (tickerData.length === 0) {
            try {
                tickerData = normalizeCandleRows(await fetchJson<unknown>(historyUrl))
                if (tickerData.length > 0) {
                    ohlcvStore.set(fallbackCacheKey, tickerData)
                }
            } catch (_error) {
                tickerData = normalizeCandleRows(ohlcvStore.get(fallbackCacheKey) ?? [])
            }
        }

        if (tickerData.length === 0) {
            isEmpty.value = true
            return
        }

        chartReady.value = true
        await nextTick()
        await nextAnimationFrame()
        if (!chartRef.value) {
            isEmpty.value = true
            chartReady.value = false
            return
        }

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
            upColor: '#2E7D5B',
            borderUpColor: '#2E7D5B',
            wickUpColor: '#2E7D5B',
            downColor: '#B4443F',
            borderDownColor: '#B4443F',
            wickDownColor: '#B4443F',
            priceFormat: {
                type: 'price',
                minMove: precision,
            },
        })

        const localOffsetSeconds = getLocalOffsetSeconds()
        const localTickerData = tickerData.map((entry) => ({
            ...entry,
            time: Number(entry.time) + localOffsetSeconds,
        }))
        await nextAnimationFrame()
        candlestickSeries.setData(localTickerData)

        for (const priceLine of props.priceLines) {
            const price = toFiniteNumber(priceLine.price)
            if (price === null || price <= 0) {
                continue
            }
            candlestickSeries.createPriceLine({
                price,
                color: priceLine.color,
                lineWidth: 2,
                lineStyle: priceLine.lineStyle,
                axisLabelVisible: true,
                title: priceLine.title,
            })
        }

        const candleMarkerData = props.markers
            .map((marker) => {
                const markerTime = normalizeMarkerTime(
                    marker.timestamp,
                    timeframe.seconds,
                    localOffsetSeconds,
                )
                if (markerTime === null) {
                    return null
                }
                if (toFiniteNumber(marker.price) !== null) {
                    return null
                }
                return {
                    time: markerTime,
                    position: marker.position,
                    color: marker.color,
                    shape: marker.shape,
                    text: marker.text,
                }
            })
            .filter((marker): marker is NormalizedTradeReplayMarker => marker !== null)

        const exactMarkerData = props.markers
            .map((marker) => {
                const markerPrice = toFiniteNumber(marker.price)
                const markerTime = normalizeExactMarkerTime(
                    marker.timestamp,
                    localOffsetSeconds,
                )
                if (markerTime === null || markerPrice === null) {
                    return null
                }
                return {
                    time: markerTime,
                    position: 'inBar' as const,
                    color: marker.color,
                    shape: marker.shape,
                    text: marker.text,
                    price: markerPrice,
                }
            })
            .filter((marker): marker is ExactTradeReplayMarker => marker !== null)
            .sort((left, right) => left.time - right.time)

        if (candleMarkerData.length > 0) {
            createSeriesMarkers(candlestickSeries, candleMarkerData)
        }

        if (exactMarkerData.length > 0) {
            // Exact-price markers need backing series data. Lightweight Charts
            // snaps markers to existing series points and does not autoscale around
            // marker-only prices, so we attach these markers to a hidden line
            // series with real time/value points.
            const exactMarkerSeries = chart.addSeries(LineSeries, {
                color: 'rgba(0, 0, 0, 0)',
                lineVisible: false,
                pointMarkersVisible: false,
                crosshairMarkerVisible: false,
                lastValueVisible: false,
                priceLineVisible: false,
                priceFormat: {
                    type: 'price',
                    minMove: precision,
                },
            })
            exactMarkerSeries.setData(
                exactMarkerData.map((marker) => ({
                    time: marker.time,
                    value: marker.price,
                    color: marker.color,
                })),
            )
            createSeriesMarkers(exactMarkerSeries, exactMarkerData)
        }

        await nextAnimationFrame()
        chart.timeScale().fitContent()
    } catch (error) {
        loadError.value = error instanceof Error
            ? error.message
            : 'Failed loading replay chart.'
        chartReady.value = false
    } finally {
        isLoading.value = false
    }
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
    width: 100%;
}

.expand-chart-frame {
    overflow: hidden;
    border-radius: inherit;
}

.expand-chart {
    height: 400px;
    width: 100%;
}

.expand-chart-empty {
    align-items: center;
    background: rgb(24, 24, 28);
    color: #ECEFEA;
    display: flex;
    font-size: 14px;
    height: 400px;
    justify-content: center;
    padding: 16px;
    text-align: center;
    width: 100%;
}

@media (max-width: 768px) {
    .expand-chart,
    .expand-chart-empty {
        height: 300px;
    }
}
</style>
