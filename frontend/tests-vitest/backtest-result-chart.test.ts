import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import BacktestResultChart from '../src/components/BacktestResultChart.vue'
import type { BacktestCandle, BacktestMarker } from '../src/helpers/backtest'

const chartLibrary = vi.hoisted(() => ({
    createChart: vi.fn(),
    createSeriesMarkers: vi.fn(),
    CandlestickSeries: Symbol('CandlestickSeries'),
    LineSeries: Symbol('LineSeries'),
}))

vi.mock('lightweight-charts', () => chartLibrary)

function candle(time: number, price: number): BacktestCandle {
    return {
        time,
        open: price,
        high: price + 1,
        low: price - 1,
        close: price + 0.5,
    }
}

const candles = [candle(1_800_000_000, 100), candle(1_800_000_060, 101)]
const markers: BacktestMarker[] = [
    {
        time: candles[0].time,
        position: 'aboveBar',
        color: '#2E7D5B',
        shape: 'arrow_up',
        text: 'take_profit',
    },
    {
        time: candles[1].time,
        position: 'belowBar',
        color: '#B4443F',
        shape: 'arrow_down',
        text: 'SIDESTEP',
    },
]

function createFakeChart() {
    const series = {
        setData: vi.fn(),
        createPriceLine: vi.fn(),
    }
    const timeScale = {
        fitContent: vi.fn(),
        getVisibleLogicalRange: vi.fn(() => ({ from: 0, to: 1 })),
        setVisibleLogicalRange: vi.fn(),
        width: vi.fn(() => 300),
        subscribeVisibleTimeRangeChange: vi.fn(),
        setVisibleRange: vi.fn(),
    }
    return {
        series,
        timeScaleApi: timeScale,
        addSeries: vi.fn(() => series),
        timeScale: vi.fn(() => timeScale),
        options: vi.fn(() => ({
            layout: { fontFamily: 'Lato', fontSize: 12 },
        })),
        remove: vi.fn(),
    }
}

function mountChart(overrides: { candles?: BacktestCandle[]; markers?: BacktestMarker[] } = {}) {
    return mount(BacktestResultChart, {
        props: {
            candles: overrides.candles ?? candles,
            markers: overrides.markers ?? markers,
            indicators: [],
        },
    })
}

describe('BacktestResultChart viewport lifecycle', () => {
    const frameCallbacks: FrameRequestCallback[] = []
    const createdCharts: ReturnType<typeof createFakeChart>[] = []
    let canvasContext: { font: string; measureText: ReturnType<typeof vi.fn> } | null

    beforeEach(() => {
        frameCallbacks.length = 0
        createdCharts.length = 0
        chartLibrary.createSeriesMarkers.mockReset()
        chartLibrary.createChart.mockReset().mockImplementation(() => {
            const fakeChart = createFakeChart()
            createdCharts.push(fakeChart)
            return fakeChart
        })
        canvasContext = {
            font: '',
            measureText: vi.fn((text: string) => ({ width: text.length * 10 })),
        }
        vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockImplementation(
            () => canvasContext as CanvasRenderingContext2D | null,
        )
        vi.stubGlobal(
            'requestAnimationFrame',
            (callback: FrameRequestCallback): number => {
                frameCallbacks.push(callback)
                return frameCallbacks.length
            },
        )
    })

    afterEach(() => {
        vi.restoreAllMocks()
        vi.unstubAllGlobals()
    })

    async function reachSizingFrame(): Promise<void> {
        await flushPromises()
        expect(frameCallbacks).toHaveLength(1)
    }

    async function paintNextFrame(): Promise<void> {
        const callback = frameCallbacks.shift()
        expect(callback).toBeDefined()
        callback?.(0)
        await flushPromises()
    }

    it('fits and pads actual boundary marker labels before marking the chart ready', async () => {
        const wrapper = mountChart()

        await reachSizingFrame()
        expect(wrapper.get('.backtest-chart').attributes('data-backtest-chart-ready')).toBe(
            undefined,
        )
        await paintNextFrame()

        const timeScale = createdCharts[0].timeScaleApi
        expect(canvasContext?.font).toBe('12px Lato')
        expect(canvasContext?.measureText).toHaveBeenCalledWith('take_profit')
        expect(canvasContext?.measureText).toHaveBeenCalledWith('SIDESTEP')
        expect(timeScale.fitContent).toHaveBeenCalledOnce()
        expect(timeScale.setVisibleLogicalRange).toHaveBeenCalledOnce()
        const paddedRange = timeScale.setVisibleLogicalRange.mock.calls[0][0]
        expect(paddedRange.from).toBeLessThan(0)
        expect(paddedRange.to).toBeGreaterThan(1)
        expect(timeScale.fitContent.mock.invocationCallOrder[0]).toBeLessThan(
            timeScale.setVisibleLogicalRange.mock.invocationCallOrder[0],
        )
        expect(wrapper.get('.backtest-chart').attributes('data-backtest-chart-ready')).toBe(
            'true',
        )
    })

    it('keeps the fitted chart when canvas text measurement is unavailable', async () => {
        canvasContext = null
        const wrapper = mountChart()

        await reachSizingFrame()
        await paintNextFrame()

        expect(createdCharts[0].timeScaleApi.fitContent).toHaveBeenCalledOnce()
        expect(
            createdCharts[0].timeScaleApi.setVisibleLogicalRange,
        ).not.toHaveBeenCalled()
        expect(wrapper.get('.backtest-chart').attributes('data-backtest-chart-ready')).toBe(
            'true',
        )
    })

    it('keeps the fitted chart when the helper cannot produce a range', async () => {
        const wrapper = mountChart()

        await reachSizingFrame()
        createdCharts[0].timeScaleApi.width.mockReturnValue(0)
        await paintNextFrame()

        expect(
            createdCharts[0].timeScaleApi.setVisibleLogicalRange,
        ).not.toHaveBeenCalled()
        expect(wrapper.get('.backtest-chart').attributes('data-backtest-chart-ready')).toBe(
            'true',
        )
    })

    it('keeps the fitted chart ready when setting marker padding throws', async () => {
        const wrapper = mountChart()

        await reachSizingFrame()
        createdCharts[0].timeScaleApi.setVisibleLogicalRange.mockImplementation(() => {
            throw new Error('range rejected')
        })
        await paintNextFrame()

        expect(createdCharts[0].timeScaleApi.fitContent).toHaveBeenCalledOnce()
        expect(wrapper.get('.backtest-chart').attributes('data-backtest-chart-ready')).toBe(
            'true',
        )
    })

    it('lets only the latest render own the sizing frame', async () => {
        const wrapper = mountChart()

        await reachSizingFrame()
        await wrapper.setProps({
            markers: [{ ...markers[0], text: 'new boundary label' }],
        })
        await flushPromises()
        expect(frameCallbacks).toHaveLength(2)
        expect(createdCharts).toHaveLength(2)

        await paintNextFrame()
        expect(createdCharts[0].remove).toHaveBeenCalledOnce()
        expect(createdCharts[0].timeScaleApi.fitContent).not.toHaveBeenCalled()

        await paintNextFrame()
        expect(createdCharts[1].timeScaleApi.fitContent).toHaveBeenCalledOnce()
        expect(wrapper.get('.backtest-chart').attributes('data-backtest-chart-ready')).toBe(
            'true',
        )
    })

    it('lets only the latest render continue after the Vue layout wait', async () => {
        const wrapper = mountChart()
        const updatedCandles = [...candles, candle(1_800_000_120, 102)]

        await wrapper.setProps({ candles: updatedCandles })
        await flushPromises()

        expect(createdCharts).toHaveLength(1)
        expect(createdCharts[0].series.setData).toHaveBeenCalledWith(
            expect.arrayContaining([
                expect.objectContaining({ time: updatedCandles[2].time }),
            ]),
        )
        expect(frameCallbacks).toHaveLength(1)
    })

    it('does not paint a chart whose sizing frame resolves after unmount', async () => {
        const wrapper = mountChart()

        await reachSizingFrame()
        wrapper.unmount()
        await paintNextFrame()

        expect(createdCharts[0].remove).toHaveBeenCalledOnce()
        expect(createdCharts[0].timeScaleApi.fitContent).not.toHaveBeenCalled()
    })

    it('does not construct a chart for an empty candle result', async () => {
        mountChart({ candles: [] })

        await flushPromises()

        expect(chartLibrary.createChart).not.toHaveBeenCalled()
        expect(frameCallbacks).toHaveLength(0)
    })
})
