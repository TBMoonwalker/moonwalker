import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import TradeReplayChart from '../src/components/TradeReplayChart.vue'
import { TIMEFRAME_CHOICES } from '../src/helpers/openTrades'

const library = vi.hoisted(() => ({
    createChart: vi.fn(), createSeriesMarkers: vi.fn(),
    CandlestickSeries: Symbol('CandlestickSeries'), LineSeries: Symbol('LineSeries'),
}))
vi.mock('lightweight-charts', () => library)
vi.mock('../src/api/client', () => ({
    fetchJson: vi.fn(async () => [{ time: 1_800_000_000, open: 100, high: 102, low: 99, close: 101 }]),
}))
vi.mock('../src/stores/ohlcv', () => ({
    useOhlcvStore: () => ({ get: () => undefined, set: vi.fn() }),
}))

afterEach(() => { vi.unstubAllGlobals(); vi.clearAllMocks() })

describe('trade replay chart synchronization lifecycle', () => {
    it.each([false, true])('cleans up before removal; interrupted render=%s', async interrupted => {
        const frames: FrameRequestCallback[] = []
        vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => frames.push(callback))
        const scale = {
            subscribeVisibleTimeRangeChange: vi.fn(),
            unsubscribeVisibleTimeRangeChange: vi.fn(),
            fitContent: vi.fn(), setVisibleRange: vi.fn(),
        }
        const chart = {
            timeScale: () => scale, remove: vi.fn(),
            addSeries: () => ({ setData: vi.fn(), createPriceLine: vi.fn() }),
        }
        library.createChart.mockReturnValue(chart)
        const wrapper = mount(TradeReplayChart, { props: {
            symbol: 'BTC/USDC', precision: 2, startTimestamp: 1_800_000_000_000,
            minTimeframe: TIMEFRAME_CHOICES[0], markers: [], priceLines: [],
        } })
        const paint = async () => {
            await flushPromises()
            expect(frames).toHaveLength(1)
            frames.shift()!(0)
            await flushPromises()
        }
        await paint() // layout and chart construction
        await paint() // candles and indicator panes
        if (interrupted) {
            wrapper.unmount()
            await paint() // pending final frame must not subscribe a removed chart
            expect(scale.subscribeVisibleTimeRangeChange).not.toHaveBeenCalled()
        } else {
            await paint()
            expect(scale.subscribeVisibleTimeRangeChange).toHaveBeenCalledOnce()
            wrapper.unmount()
            expect(scale.unsubscribeVisibleTimeRangeChange).toHaveBeenCalledExactlyOnceWith(
                scale.subscribeVisibleTimeRangeChange.mock.calls[0][0],
            )
            expect(scale.unsubscribeVisibleTimeRangeChange.mock.invocationCallOrder[0]).toBeLessThan(
                chart.remove.mock.invocationCallOrder[0],
            )
        }
        expect(chart.remove).toHaveBeenCalledOnce()
    })
})
