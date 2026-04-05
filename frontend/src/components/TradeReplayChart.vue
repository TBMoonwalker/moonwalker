<template>
    <n-card class="expand-chart-card" content-style="padding: 0;">
        <div class="expand-chart-frame">
            <div ref="chartRef" class="expand-chart" />
        </div>
    </n-card>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import {
    CandlestickSeries,
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
    position: 'aboveBar' | 'belowBar'
    color: string
    shape: 'arrowUp' | 'arrowDown' | 'circle'
    text: string
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

const chartRef = ref<HTMLElement | null>(null)
const ohlcvStore = useOhlcvStore()
let chart: ReturnType<typeof createChart> | null = null

function toFiniteNumber(value: number | string | null | undefined): number | null {
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : null
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
    let normalized = Math.trunc(Number(timestamp) / 1000)
    if (!Number.isFinite(normalized)) {
        return null
    }
    normalized -= normalized % seconds
    normalized += localOffsetSeconds
    return normalized
}

async function initChart(): Promise<void> {
    if (!chartRef.value) {
        return
    }

    const beginTimestamp = toFiniteNumber(props.startTimestamp)
    if (beginTimestamp === null) {
        return
    }

    const endTimestamp = toFiniteNumber(props.endTimestamp)
    const [symbol, currency] = splitTradeSymbol(props.symbol)
    const precision = createDecimal(props.precision)
    const timeframe = selectTimeframe()
    const historyStart = Math.max(
        0,
        beginTimestamp - timeframe.seconds * PRE_ROLL_CANDLES * 1000,
    )
    const historyEnd =
        endTimestamp === null
            ? null
            : endTimestamp + timeframe.seconds * POST_ROLL_CANDLES * 1000

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
        upColor: 'rgb(99, 226, 183)',
        borderUpColor: 'rgb(99, 226, 183)',
        wickUpColor: 'rgb(99, 226, 183)',
        downColor: 'rgb(224, 108, 117)',
        borderDownColor: 'rgb(224, 108, 117)',
        wickDownColor: 'rgb(224, 108, 117)',
        priceFormat: {
            type: 'price',
            minMove: precision,
        },
    })

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
    if (archiveUrl && archiveCacheKey) {
        try {
            tickerData = await fetchJson<Array<Record<string, number>>>(archiveUrl)
            if (Array.isArray(tickerData) && tickerData.length > 0) {
                ohlcvStore.set(archiveCacheKey, tickerData)
            } else {
                tickerData = []
            }
        } catch (_error) {
            tickerData = ohlcvStore.get(archiveCacheKey) ?? []
        }
    }

    if (tickerData.length === 0) {
        try {
            tickerData = await fetchJson<Array<Record<string, number>>>(historyUrl)
            ohlcvStore.set(fallbackCacheKey, tickerData)
        } catch (_error) {
            tickerData = ohlcvStore.get(fallbackCacheKey) ?? []
        }
    }

    const localOffsetSeconds = getLocalOffsetSeconds()
    const localTickerData = tickerData.map((entry) => ({
        ...entry,
        time: Number(entry.time) + localOffsetSeconds,
    }))
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

    const markerData = props.markers
        .map((marker) => {
            const markerTime = normalizeMarkerTime(
                marker.timestamp,
                timeframe.seconds,
                localOffsetSeconds,
            )
            if (markerTime === null) {
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
        .filter((marker) => marker !== null)

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

@media (max-width: 768px) {
    .expand-chart {
        height: 300px;
    }
}
</style>
