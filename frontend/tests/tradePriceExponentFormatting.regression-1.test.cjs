const assert = require('node:assert/strict')
const test = require('node:test')

const { loadFrontendModule } = require('./helpers/loadFrontendModule.cjs')
const { createPinia, setActivePinia } = require('pinia')

const { useTradesStore } = loadFrontendModule('src/stores/trades.ts')

function createStore() {
    setActivePinia(createPinia())
    return useTradesStore()
}

test('normalizeOpenTradeRow formats exponent-notation prices without crashing', () => {
    const store = createStore()

    const row = store.normalizeOpenTradeRow({
        id: 1,
        symbol: 'TINY/USDC',
        amount: 1e-7,
        cost: 0.5,
        tp_price: 1e-7,
        avg_price: 2.25,
        current_price: 1e-7,
        safetyorders: [],
    })

    assert.equal(row.tp_price, '0.0000001')
    assert.equal(row.current_price, '0.0000001')
    assert.equal(row.amount, '0.0000001')
    assert.equal(row.precision, 7)
})

test('setClosedTrades formats exponent-notation prices with the full digit count', () => {
    const store = createStore()

    store.setClosedTrades([
        {
            id: 2,
            symbol: 'TINY/USDC',
            amount: 1e-7,
            cost: 0.123456,
            tp_price: 1e-7,
            avg_price: 2.5,
            profit: 1e-7,
            profit_percent: 1e-7,
            open_date: '2026-01-01',
            close_date: '2026-01-02',
            duration: '{"days":0,"hours":1,"minutes":0,"seconds":0}',
        },
    ])

    const row = store.closedTrades[0]
    // tp_price uses the wider closed-trade precision (up to 8 digits).
    assert.equal(row.tp_price, '0.0000001')
    assert.equal(row.cost, '0.123456')
    assert.equal(row.amount, '0.0000001')
    // profit is capped at 6 digits by design, so the exponent shift rounds
    // to zero instead of crashing the row mapping.
    assert.equal(row.profit, '0.000000')
    assert.equal(row.precision, 7)
})

test('formatting keeps the existing behavior for plain decimals and integers', () => {
    const store = createStore()

    store.setClosedTrades([
        {
            id: 3,
            symbol: 'BTC/USDC',
            amount: 0.5,
            cost: 100.5,
            tp_price: 2,
            avg_price: 1.25,
            profit: 10,
            profit_percent: 5,
            open_date: '2026-01-01',
            close_date: '2026-01-02',
            duration: '{"days":0,"hours":0,"minutes":0,"seconds":1}',
        },
    ])

    const row = store.closedTrades[0]
    assert.equal(row.cost, '100.50')
    assert.equal(row.tp_price, '2.00')
    assert.equal(row.avg_price, '1.25')
    assert.equal(row.amount, '0.5')
    assert.equal(row.profit, '10.00')
    assert.equal(row.precision, 2)
})
