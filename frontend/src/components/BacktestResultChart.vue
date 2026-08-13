<template>
    <div class="backtest-chart-frame">
        <div v-if="candles.length === 0" class="backtest-chart-empty">
            <span>No candles returned</span>
        </div>
        <div v-else class="backtest-chart-stack">
            <div v-if="priceIndicators.length > 0" class="chart-legend">
                <span
                    v-for="series in priceIndicators"
                    :key="series.key"
                    class="legend-item"
                >
                    <i :style="{ background: series.color }" />
                    {{ series.label }}
                </span>
            </div>
            <div ref="chartRef" class="backtest-chart" />
            <section
                v-for="pane in indicatorPanes"
                :key="pane.key"
                class="indicator-pane"
            >
                <header class="indicator-pane-header">
                    <strong>{{ pane.label }}</strong>
                    <span
                        v-for="series in pane.series"
                        :key="series.key"
                        class="legend-item"
                    >
                        <i :style="{ background: series.color }" />
                        {{ series.label }}
                    </span>
                </header>
                <div
                    :ref="(element) => setIndicatorChartRef(pane.key, element)"
                    class="indicator-chart"
                />
            </section>
        </div>
    </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import {
    CandlestickSeries,
    LineSeries,
    createChart,
    createSeriesMarkers,
    type CandlestickData,
    type LineData,
    type SeriesMarker,
    type UTCTimestamp,
} from 'lightweight-charts'

import {
    normalizeBacktestMarkerShape,
    normalizeBacktestTimestampSeconds,
    type BacktestCandle,
    type BacktestIndicatorSeries,
    type BacktestMarker,
} from '../helpers/backtest'
import {
    expandBoundaryLogicalRange,
    selectBoundaryMarkerTextWidths,
} from '../helpers/backtestChartViewport'
import {
    getIndicatorPanes,
    getPriceIndicatorSeries,
    renderIndicatorSeries,
    withDistinctIndicatorColors,
    type IndicatorPane,
} from '../helpers/tradingViewIndicators'

const props = defineProps<{
    candles: BacktestCandle[]
    markers: BacktestMarker[]
    indicators: BacktestIndicatorSeries[]
}>()

const chartRef = ref<HTMLElement | null>(null)
const indicatorChartRefs = new Map<string, HTMLElement>()
let chart: ReturnType<typeof createChart> | null = null
let indicatorCharts: Array<ReturnType<typeof createChart>> = []
let isSynchronizingTimeScale = false
let activeRenderToken: object | null = null

const MARKER_EDGE_GUTTER_PX = 8
const MARKER_SHAPE_HALF_WIDTH_PX = 8

const displayIndicators = computed<BacktestIndicatorSeries[]>(() =>
    withDistinctIndicatorColors(props.indicators),
)

const priceIndicators = computed(() =>
    getPriceIndicatorSeries(displayIndicators.value),
)

const indicatorPanes = computed<IndicatorPane[]>(() =>
    getIndicatorPanes(displayIndicators.value),
)

function setIndicatorChartRef(key: string, element: unknown): void {
    if (element instanceof HTMLElement) {
        indicatorChartRefs.set(key, element)
    } else {
        indicatorChartRefs.delete(key)
    }
}

function removeCharts(): void {
    activeRenderToken = null
    chartRef.value?.removeAttribute('data-backtest-chart-ready')
    if (chart) {
        chart.remove()
        chart = null
    }
    for (const indicatorChart of indicatorCharts) {
        indicatorChart.remove()
    }
    indicatorCharts = []
}

function waitForSizingFrame(): Promise<void> {
    return new Promise((resolve) => {
        requestAnimationFrame(() => resolve())
    })
}

function requiredBoundaryPaddingPx(textWidthPx: number | null): number {
    if (textWidthPx === null) {
        return 0
    }
    return Math.ceil(
        textWidthPx / 2 + MARKER_SHAPE_HALF_WIDTH_PX + MARKER_EDGE_GUTTER_PX,
    )
}

function chartOptions() {
    return {
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
    }
}

function synchronizeTimeScales(charts: Array<ReturnType<typeof createChart>>): void {
    for (const sourceChart of charts) {
        sourceChart.timeScale().subscribeVisibleTimeRangeChange((range) => {
            if (!range || isSynchronizingTimeScale) {
                return
            }
            isSynchronizingTimeScale = true
            for (const targetChart of charts) {
                if (targetChart !== sourceChart) {
                    targetChart.timeScale().setVisibleRange(range)
                }
            }
            isSynchronizingTimeScale = false
        })
    }
}

async function renderChart(): Promise<void> {
    removeCharts()
    const renderToken = {}
    activeRenderToken = renderToken
    await nextTick()
    if (
        activeRenderToken !== renderToken ||
        !chartRef.value ||
        props.candles.length === 0
    ) {
        return
    }

    const element = chartRef.value
    const priceChart = createChart(element, chartOptions())
    chart = priceChart

    const candlestickSeries = priceChart.addSeries(CandlestickSeries, {
        upColor: '#2E7D5B',
        borderUpColor: '#2E7D5B',
        wickUpColor: '#2E7D5B',
        downColor: '#B4443F',
        borderDownColor: '#B4443F',
        wickDownColor: '#B4443F',
    })

    const candleData: CandlestickData<UTCTimestamp>[] = props.candles.map(
        (candle) => ({
            time: normalizeBacktestTimestampSeconds(candle.time),
            open: Number(candle.open),
            high: Number(candle.high),
            low: Number(candle.low),
            close: Number(candle.close),
        }),
    )
    candlestickSeries.setData(candleData)

    for (const series of priceIndicators.value) {
        renderIndicatorSeries(priceChart, series)
    }

    const markerData: SeriesMarker<UTCTimestamp>[] = props.markers
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

    for (const pane of indicatorPanes.value) {
        const element = indicatorChartRefs.get(pane.key)
        if (!element) {
            continue
        }
        const indicatorChart = createChart(element, chartOptions())
        const firstSeries = pane.series[0]
        const anchorValue = firstSeries.values[0]?.value
        if (anchorValue !== undefined && props.candles.length > 0) {
            const timelineAnchor = indicatorChart.addSeries(LineSeries, {
                color: 'transparent',
                lineVisible: false,
                pointMarkersVisible: false,
                crosshairMarkerVisible: false,
                priceLineVisible: false,
                lastValueVisible: false,
            })
            timelineAnchor.setData(
                <LineData<UTCTimestamp>[]>[
                    {
                        time: normalizeBacktestTimestampSeconds(props.candles[0].time),
                        value: anchorValue,
                    },
                    {
                        time: normalizeBacktestTimestampSeconds(
                            props.candles[props.candles.length - 1].time,
                        ),
                        value: anchorValue,
                    },
                ],
            )
        }
        const renderedSeries = pane.series.map((series) =>
            renderIndicatorSeries(indicatorChart, series),
        )
        const referenceValue = pane.key === 'rsi' ? 50 : pane.key === 'macd' ? 0 : null
        if (referenceValue !== null && renderedSeries.length > 0) {
            renderedSeries[0].createPriceLine({
                price: referenceValue,
                color: 'rgba(138, 148, 141, 0.7)',
                lineWidth: 1,
                lineStyle: 2,
                axisLabelVisible: true,
                title: pane.key === 'rsi' ? '50' : '0',
            })
        }
        indicatorCharts.push(indicatorChart)
    }

    synchronizeTimeScales([priceChart, ...indicatorCharts])

    await waitForSizingFrame()
    if (activeRenderToken !== renderToken || chart !== priceChart) {
        return
    }

    const timeScale = priceChart.timeScale()
    timeScale.fitContent()
    try {
        const canvasContext = document.createElement('canvas').getContext('2d')
        const fittedRange = timeScale.getVisibleLogicalRange()
        if (canvasContext && fittedRange) {
            const { fontFamily, fontSize } = priceChart.options().layout
            canvasContext.font = `${fontSize}px ${fontFamily}`
            const boundaryTextWidths = selectBoundaryMarkerTextWidths({
                firstCandleTime: Number(candleData[0].time),
                lastCandleTime: Number(candleData[candleData.length - 1].time),
                markers: markerData.map((marker) => ({
                    time: Number(marker.time),
                    textWidthPx: canvasContext.measureText(marker.text ?? '').width,
                })),
            })
            if (boundaryTextWidths) {
                const paddedRange = expandBoundaryLogicalRange({
                    fittedRange,
                    firstLogicalIndex: 0,
                    lastLogicalIndex: candleData.length - 1,
                    plotWidthPx: timeScale.width(),
                    requiredLeftPx: requiredBoundaryPaddingPx(
                        boundaryTextWidths.leftTextWidthPx,
                    ),
                    requiredRightPx: requiredBoundaryPaddingPx(
                        boundaryTextWidths.rightTextWidthPx,
                    ),
                })
                if (paddedRange) {
                    timeScale.setVisibleLogicalRange(paddedRange)
                }
            }
        }
    } catch {
        // Marker padding is best-effort; the fitted chart remains usable.
    }
    element.dataset.backtestChartReady = 'true'
}

onMounted(() => {
    void renderChart()
})

watch(
    () => [props.candles, props.markers, props.indicators],
    () => {
        void renderChart()
    },
    { deep: true },
)

onUnmounted(removeCharts)
</script>

<style scoped>
.backtest-chart-frame {
    width: 100%;
    overflow: hidden;
    border: 1px solid var(--mw-color-border);
    border-radius: var(--mw-radius-md);
    background: var(--mw-surface-card-subtle);
}

.backtest-chart-stack {
    display: grid;
}

.chart-legend,
.indicator-pane-header {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px 14px;
    padding: 8px 12px 0;
    color: var(--mw-color-text-secondary);
    font-size: 0.78rem;
}

.legend-item {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    white-space: nowrap;
}

.legend-item i {
    width: 14px;
    height: 2px;
    border-radius: 1px;
}

.backtest-chart {
    width: 100%;
    height: 420px;
}

.indicator-pane {
    border-top: 1px solid var(--mw-color-border);
}

.indicator-pane-header strong {
    margin-right: 4px;
    color: var(--mw-color-text-primary);
    font-size: 0.78rem;
}

.indicator-chart {
    width: 100%;
    height: 128px;
}

.backtest-chart-empty {
    display: grid;
    min-height: 420px;
    place-items: center;
    color: var(--mw-color-text-muted);
    font-size: 0.95rem;
}

@media (max-width: 767px) {
    .backtest-chart {
        height: 320px;
    }

    .indicator-chart {
        height: 116px;
    }

    .backtest-chart-empty {
        min-height: 320px;
    }
}
</style>
