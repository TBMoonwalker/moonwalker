const assert = require('node:assert/strict')
const test = require('node:test')

const { loadFrontendModule } = require('./helpers/loadFrontendModule.cjs')

const {
    DEFAULT_MIN_TIMEFRAME,
    calculateSoPercentage,
    formatOrderAmount,
    formatPrice,
    getPreviousBuyPrice,
    getSafetyOrderCount,
    getUnsellableMessage,
    parseTimeframeSeconds,
    resolveMinTimeframe,
} = loadFrontendModule('src/helpers/openTrades.ts')

test('parseTimeframeSeconds normalizes supported units', () => {
    assert.equal(parseTimeframeSeconds('5min'), 300)
    assert.equal(parseTimeframeSeconds('4h'), 14400)
    assert.equal(parseTimeframeSeconds('1D'), 86400)
    assert.equal(parseTimeframeSeconds('bad-value'), null)
})

test('resolveMinTimeframe falls back and rounds up to supported choices', () => {
    assert.deepEqual(resolveMinTimeframe(null), DEFAULT_MIN_TIMEFRAME)
    assert.deepEqual(resolveMinTimeframe('7m'), {
        timerange: '15min',
        seconds: 15 * 60,
    })
    assert.deepEqual(resolveMinTimeframe('9h'), {
        timerange: '1D',
        seconds: 24 * 60 * 60,
    })
})

test('open trade helpers format unsellable trade details', () => {
    const row = {
        id: 1,
        symbol: 'BTC/USDT',
        amount: 0.1,
        cost: 2500,
        profit: 10,
        profit_percent: 0.4,
        current_price: 26000,
        tp_price: 27000,
        avg_price: 25000,
        so_count: 2,
        open_date: '2024-01-01 12:00:00',
        baseorder: {
            id: 1,
            timestamp: '1000',
            ordersize: 100,
            amount: 0.01,
            symbol: 'BTC/USDT',
            price: 25000,
        },
        safetyorder: [
            {
                id: 2,
                timestamp: '2000',
                ordersize: 150,
                amount: 0.02,
                symbol: 'BTC/USDT',
                price: 24500,
            },
        ],
        precision: 2,
        unsellable_amount: 0.00012345,
        unsellable_reason: 'min-notional',
        unsellable_min_notional: 10,
        unsellable_estimated_notional: 3.2,
    }

    assert.equal(getSafetyOrderCount(row), 1)
    assert.match(getUnsellableMessage(row), /Unsellable remainder for BTC\/USDT/)
    assert.match(getUnsellableMessage(row), /Minimum notional required/)
})

test('open trade helpers derive order prices and percentages safely', () => {
    const row = {
        id: 1,
        symbol: 'ETH/USDT',
        amount: 1,
        cost: 1000,
        profit: 20,
        profit_percent: 2,
        current_price: 1100,
        tp_price: 1200,
        avg_price: 1000,
        so_count: 0,
        open_date: '2024-01-01 12:00:00',
        baseorder: {
            id: 1,
            timestamp: '1000',
            ordersize: 100,
            amount: 0.1,
            symbol: 'ETH/USDT',
            price: 1000,
        },
        safetyorder: [
            {
                id: 2,
                timestamp: '2000',
                ordersize: 110,
                amount: 0.11,
                symbol: 'ETH/USDT',
                price: 950,
            },
            {
                id: 3,
                timestamp: '3000',
                ordersize: 120,
                amount: 0.12,
                symbol: 'ETH/USDT',
                price: 900,
            },
        ],
        precision: 2,
    }

    assert.equal(getPreviousBuyPrice(row), 900)
    assert.equal(calculateSoPercentage(810, 900), -10)
    assert.equal(formatOrderAmount(12.345), '12.35')
    assert.equal(formatPrice(12.34000000), '12.34')
})
