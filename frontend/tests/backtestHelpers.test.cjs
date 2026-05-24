const assert = require('node:assert/strict')
const test = require('node:test')

const { loadFrontendModule } = require('./helpers/loadFrontendModule.cjs')

const {
    buildBacktestRequest,
    computeBacktestComparison,
    createDefaultBacktestForm,
    createDefaultBacktestRange,
    normalizeBacktestMarkerShape,
    normalizeBacktestTimestampSeconds,
} = loadFrontendModule('src/helpers/backtest.ts')

test('buildBacktestRequest maps UI state to the backend contract', () => {
    const form = createDefaultBacktestForm()
    form.strategySlug = 'ema20_swing'
    form.symbol = ' BTC/USDT '
    const request = buildBacktestRequest(form, [1_700_000_000_000, 1_700_003_600_000])

    assert.equal(request.symbol, 'BTC/USDT')
    assert.equal(request.strategy_slug, 'ema20_swing')
    assert.equal(request.timeframe, '1h')
    assert.equal(request.start_date, 1_700_000_000_000)
    assert.equal(request.end_date, 1_700_003_600_000)
    assert.equal(request.base_order_size, 20)
    assert.equal(request.max_safety_orders, 5)
})

test('createDefaultBacktestRange starts one week before the end timestamp', () => {
    const now = 1_700_000_000_000
    const [start, end] = createDefaultBacktestRange(now)

    assert.equal(end, now)
    assert.equal(end - start, 7 * 24 * 60 * 60 * 1000)
})

test('computeBacktestComparison returns deltas for previous-run footer', () => {
    const current = {
        stats: {
            summary: {
                total_trades: 4,
                total_profit: 12.5,
                win_rate: 75,
            },
        },
    }
    const previous = {
        stats: {
            summary: {
                total_trades: 2,
                total_profit: 10,
                win_rate: 50,
            },
        },
    }

    assert.deepEqual(computeBacktestComparison(current, previous), {
        tradesDelta: 2,
        profitDelta: 2.5,
        winRateDelta: 25,
    })
})

test('normalizeBacktestMarkerShape accepts backend and chart spellings', () => {
    assert.equal(normalizeBacktestMarkerShape('arrow_up'), 'arrowUp')
    assert.equal(normalizeBacktestMarkerShape('arrow_down'), 'arrowDown')
    assert.equal(normalizeBacktestMarkerShape('arrowUp'), 'arrowUp')
    assert.equal(normalizeBacktestMarkerShape('circle'), 'circle')
})

test('normalizeBacktestTimestampSeconds accepts milliseconds and seconds', () => {
    assert.equal(normalizeBacktestTimestampSeconds(1_700_000_000_000), 1_700_000_000)
    assert.equal(normalizeBacktestTimestampSeconds(1_700_000_000), 1_700_000_000)
})
