<template>
    <div class="backtest-chart-frame">
        <div v-if="candles.length === 0" class="backtest-chart-empty">
            <span>No candles returned</span>
        </div>
        <div v-else ref="chartRef" class="backtest-chart" />
    </div>
</template>

<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import {
    CandlestickSeries,
    createChart,
    createSeriesMarkers,
} from 'lightweight-charts'

import {
    normalizeBacktestMarkerShape,
    normalizeBacktestTimestampSeconds,
    type BacktestCandle,
    type BacktestMarker,
} from '../helpers/backtest'

const props = defineProps<{
    candles: BacktestCandle[]
    markers: BacktestMarker[]
}>()

const chartRef = ref<HTMLElement | null>(null)
let chart: ReturnType<typeof createChart> | null = null

function removeChart(): void {
    if (chart) {
        chart.remove()
        chart = null
    }
}

async function renderChart(): Promise<void> {
    removeChart()
    await nextTick()
    if (!chartRef.value || props.candles.length === 0) {
        return
    }

    chart = createChart(chartRef.value, {
        autoSize: true,
        layout: {
            background: { color: 'transparent' },
            textColor: getComputedStyle(document.documentElement)
                .getPropertyValue('--mw-color-text-secondary')
                .trim(),
        },
        grid: {
            vertLines: { color: 'rgba(138, 148, 141, 0.12)' },
            horzLines: { color: 'rgba(138, 148, 141, 0.12)' },
        },
        timeScale: {
            borderVisible: false,
            timeVisible: true,
        },
        rightPriceScale: {
            borderVisible: false,
        },
        handleScroll: true,
        handleScale: true,
    })

    const candlestickSeries = chart.addSeries(CandlestickSeries, {
        upColor: '#2E7D5B',
        borderUpColor: '#2E7D5B',
        wickUpColor: '#2E7D5B',
        downColor: '#B4443F',
        borderDownColor: '#B4443F',
        wickDownColor: '#B4443F',
    })

    candlestickSeries.setData(
        props.candles.map((candle) => ({
            time: normalizeBacktestTimestampSeconds(candle.time),
            open: Number(candle.open),
            high: Number(candle.high),
            low: Number(candle.low),
            close: Number(candle.close),
        })) as any[],
    )

    const markerData = props.markers
        .map((marker) => ({
            time: normalizeBacktestTimestampSeconds(marker.time),
            position: marker.position,
            color: marker.color,
            shape: normalizeBacktestMarkerShape(marker.shape),
            text: marker.text,
        }))
        .sort((left, right) => left.time - right.time)

    if (markerData.length > 0) {
        createSeriesMarkers(candlestickSeries, markerData as any[])
    }

    chart.timeScale().fitContent()
}

onMounted(() => {
    void renderChart()
})

watch(
    () => [props.candles, props.markers],
    () => {
        void renderChart()
    },
    { deep: true },
)

onUnmounted(removeChart)
</script>

<style scoped>
.backtest-chart-frame {
    width: 100%;
    min-height: 420px;
    overflow: hidden;
    border: 1px solid var(--mw-color-border);
    border-radius: var(--mw-radius-md);
    background: var(--mw-surface-card-subtle);
}

.backtest-chart {
    width: 100%;
    height: 420px;
}

.backtest-chart-empty {
    display: grid;
    min-height: 420px;
    place-items: center;
    color: var(--mw-color-text-muted);
    font-size: 0.95rem;
}

@media (max-width: 768px) {
    .backtest-chart-frame {
        min-height: 320px;
    }

    .backtest-chart {
        height: 320px;
    }

    .backtest-chart-empty {
        min-height: 320px;
    }
}
</style>
