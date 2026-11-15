import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import TradeReplayChart from '../src/components/TradeReplayChart.vue'
import { fetchJson } from '../src/api/client'
import { TIMEFRAME_CHOICES } from '../src/helpers/openTrades'
import type { BacktestIndicatorSeries } from '../src/helpers/backtest'

const library = vi.hoisted(() => {
    const chart = {
        timeScale: () => ({
            subscribeVisibleTimeRangeChange: () => {},
            unsubscribeVisibleTimeRangeChange: () => {},
            fitContent: () => {},
            setVisibleRange: () => {},
        }),
        remove: () => {},
        addSeries: () => ({ setData: () => {}, createPriceLine: () => {} }),
    }
    return {
        createChart: vi.fn(() => chart),
        createSeriesMarkers: vi.fn(),
        CandlestickSeries: Symbol('CandlestickSeries'),
        LineSeries: Symbol('LineSeries'),
    }
})
const fixtures = vi.hoisted(() => ({
    candles: [
        { time: 1_800_000_000, open: 100, high: 102, low: 99, close: 101 },
    ] as unknown[],
    indicators: {} as unknown,
}))
vi.mock('lightweight-charts', () => library)
vi.mock('../src/api/client', () => ({
    fetchJson: vi.fn(async (url: string) => {
        if (url.startsWith('/trades/replay/indicators/')) {
            return fixtures.indicators
        }
        return fixtures.candles
    }),
}))
vi.mock('../src/stores/ohlcv', () => ({
    useOhlcvStore: () => ({ get: () => undefined, set: vi.fn() }),
}))

const CANDLE_ROWS = fixtures.candles
const CAPTION_TEXT = 'Indicator overlays unavailable for this trade.'
const PRICE_SERIES: BacktestIndicatorSeries = {
    key: 'ema', label: 'EMA', pane: 'price', renderer: 'line',
    color: '#E2A72E', values: [{ time: 1_800_000_000, value: 100 }],
}

const baseProps = {
    symbol: 'BTC/USDC', precision: 2, startTimestamp: 1_800_000_000_000,
    minTimeframe: TIMEFRAME_CHOICES[0], markers: [], priceLines: [],
}

type Frames = FrameRequestCallback[]

function createPaint(frames: Frames): () => Promise<void> {
    return async () => {
        await flushPromises()
        const pending = frames.shift()
        if (pending) pending(0)
        await flushPromises()
    }
}

async function mountChart(
    props: Record<string, unknown> = {},
): Promise<{ wrapper: VueWrapper; paint: () => Promise<void>; frames: Frames }> {
    const frames: Frames = []
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
        frames.push(callback)
    })
    const wrapper = mount(TradeReplayChart, { props: { ...baseProps, ...props } })
    const paint = createPaint(frames)
    await paint()
    await paint()
    await paint()
    return { wrapper, paint, frames }
}

afterEach(() => {
    vi.unstubAllGlobals()
    vi.clearAllMocks()
    vi.restoreAllMocks()
    fixtures.candles = CANDLE_ROWS
    fixtures.indicators = { result: { indicators: [] } }
})

describe('trade replay indicator unavailable notice', () => {
    it('shows the muted caption when the indicator fetch yields no series', async () => {
        fixtures.indicators = { result: { indicators: [] } }
        const { wrapper } = await mountChart({
            dealId: '11111111-1111-1111-1111-111111111111',
        })
        const caption = wrapper.find('.indicator-unavailable')
        expect(caption.exists()).toBe(true)
        expect(caption.text()).toBe(CAPTION_TEXT)
        expect(caption.attributes('role')).toBe('status')
        expect(wrapper.find('.expand-chart-empty').exists()).toBe(false)
        expect(library.createChart).toHaveBeenCalled()
    })

    it('shows the muted caption when the indicator fetch fails', async () => {
        const failure = new Error('Request failed: 404 Not Found')
        fixtures.indicators = Promise.reject(failure)
        const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
        const { wrapper } = await mountChart({
            dealId: '11111111-1111-1111-1111-111111111111',
        })
        expect(wrapper.find('.indicator-unavailable').text()).toBe(CAPTION_TEXT)
        expect(wrapper.find('.expand-chart-empty').exists()).toBe(false)
        expect(library.createChart).toHaveBeenCalled()
        expect(warnSpy).toHaveBeenCalledWith(
            'Failed loading replay indicators:',
            failure,
        )
    })

    it('shows the muted caption for legacy rows without a deal id and skips the fetch', async () => {
        const { wrapper } = await mountChart()
        expect(wrapper.find('.indicator-unavailable').text()).toBe(CAPTION_TEXT)
        expect(wrapper.find('.expand-chart-empty').exists()).toBe(false)
        const indicatorCalls = vi
            .mocked(fetchJson)
            .mock.calls
            .filter(([url]) => String(url).startsWith('/trades/replay/indicators/'))
        expect(indicatorCalls).toHaveLength(0)
        expect(library.createChart).toHaveBeenCalled()
    })

    it('hides the caption when indicator series are present', async () => {
        fixtures.indicators = { result: { indicators: [PRICE_SERIES] } }
        const { wrapper } = await mountChart({
            dealId: '11111111-1111-1111-1111-111111111111',
        })
        expect(wrapper.find('.indicator-unavailable').exists()).toBe(false)
        expect(wrapper.find('.chart-legend').exists()).toBe(true)
        expect(wrapper.find('.expand-chart-empty').exists()).toBe(false)
        expect(library.createChart).toHaveBeenCalled()
    })

    it('keeps the empty-candle message as the only state when no candles exist', async () => {
        fixtures.candles = []
        const { wrapper } = await mountChart({
            dealId: '11111111-1111-1111-1111-111111111111',
        })
        expect(wrapper.find('.expand-chart-empty').text()).toBe(
            'No candle data available for this replay window.',
        )
        expect(wrapper.find('.indicator-unavailable').exists()).toBe(false)
        expect(library.createChart).not.toHaveBeenCalled()
    })
})
