import {
    HistogramSeries,
    LineSeries,
    createChart,
} from 'lightweight-charts'

import {
    normalizeBacktestTimestampSeconds,
    type BacktestIndicatorPane,
    type BacktestIndicatorSeries,
} from './backtest'

export interface IndicatorPane {
    key: Exclude<BacktestIndicatorPane, 'price'>
    label: string
    series: BacktestIndicatorSeries[]
}

const INDICATOR_DISPLAY_COLORS = [
    '#E2A72E',
    '#4FA3C7',
    '#63B77D',
    '#D86B63',
    '#B48AD6',
    '#D7C85F',
    '#6CC3B0',
    '#F08C4B',
] as const

export function withDistinctIndicatorColors(
    indicators: BacktestIndicatorSeries[],
): BacktestIndicatorSeries[] {
    const paneCounts = new Map<BacktestIndicatorPane, number>()
    return indicators.map((series) => {
        const paneIndex = paneCounts.get(series.pane) ?? 0
        paneCounts.set(series.pane, paneIndex + 1)
        return {
            ...series,
            color: INDICATOR_DISPLAY_COLORS[
                paneIndex % INDICATOR_DISPLAY_COLORS.length
            ],
        }
    })
}

export function getPriceIndicatorSeries(
    indicators: BacktestIndicatorSeries[],
): BacktestIndicatorSeries[] {
    return indicators.filter((series) => series.pane === 'price')
}

export function getIndicatorPanes(
    indicators: BacktestIndicatorSeries[],
): IndicatorPane[] {
    return (
        [
            ['rsi', 'RSI'],
            ['bandwidth', 'Bandwidth %'],
            ['macd', 'MACD'],
        ] as const
    )
        .map(([key, label]) => ({
            key,
            label,
            series: indicators.filter((series) => series.pane === key),
        }))
        .filter((pane) => pane.series.length > 0)
}

export function normalizedIndicatorValues(
    series: BacktestIndicatorSeries,
    timeOffsetSeconds = 0,
) {
    return series.values.map((value) => ({
        time: normalizeBacktestTimestampSeconds(value.time) + timeOffsetSeconds,
        value: Number(value.value),
    }))
}

export interface RenderIndicatorSeriesOptions {
    priceMarkersVisible?: boolean
    priceLineVisible?: boolean
}

export function renderIndicatorSeries(
    targetChart: ReturnType<typeof createChart>,
    series: BacktestIndicatorSeries,
    timeOffsetSeconds = 0,
    options: RenderIndicatorSeriesOptions = {},
) {
    const priceMarkersVisible = options.priceMarkersVisible ?? false
    const priceLineVisible = options.priceLineVisible ?? false
    if (series.renderer === 'histogram') {
        const histogram = targetChart.addSeries(HistogramSeries, {
            color: series.color,
            priceLineVisible,
            lastValueVisible: priceMarkersVisible,
        })
        histogram.setData(
            normalizedIndicatorValues(series, timeOffsetSeconds) as any[],
        )
        return histogram
    }
    const line = targetChart.addSeries(LineSeries, {
        color: series.color,
        lineWidth: 2,
        priceLineVisible,
        lastValueVisible: priceMarkersVisible,
    })
    line.setData(normalizedIndicatorValues(series, timeOffsetSeconds) as any[])
    return line
}
