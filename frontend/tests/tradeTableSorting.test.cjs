const assert = require('node:assert/strict')
const test = require('node:test')

process.env.TZ = 'Europe/Vienna'

const { loadFrontendModule } = require('./helpers/loadFrontendModule.cjs')

const {
    resolveTradeSortTimestamp,
    resolveTradeTableSortState,
    sortTradeRows,
} = loadFrontendModule('src/helpers/tradeTable.ts')

test('trade-table sort state normalizes Naive sorter payloads', () => {
    assert.deepEqual(
        resolveTradeTableSortState({
            columnKey: 'profit_percent',
            order: 'descend',
        }),
        {
            columnKey: 'profit_percent',
            order: 'descend',
        },
    )
    assert.equal(
        resolveTradeTableSortState({
            columnKey: 'profit_percent',
            order: false,
        }),
        null,
    )
})

test('trade-table sorting handles numeric and timezone-less date values', () => {
    const rows = [
        {
            symbol: 'BTC/USDT',
            profit_percent: 4.2,
            open_date: '2026-04-26 21:57:41',
        },
        {
            symbol: 'ADA/USDT',
            profit_percent: -1.3,
            open_date: '2026-04-25 21:57:41',
        },
        {
            symbol: 'ETH/USDT',
            profit_percent: 1.8,
            open_date: '2026-04-27 21:57:41',
        },
    ]

    const sortedByProfit = sortTradeRows(
        rows,
        {
            columnKey: 'profit_percent',
            order: 'descend',
        },
        {
            profit_percent: {
                kind: 'number',
                value: (row) => row.profit_percent,
            },
        },
    )
    assert.deepEqual(
        sortedByProfit.map((row) => row.symbol),
        ['BTC/USDT', 'ETH/USDT', 'ADA/USDT'],
    )

    const sortedByOpened = sortTradeRows(
        rows,
        {
            columnKey: 'open_date',
            order: 'ascend',
        },
        {
            open_date: {
                kind: 'date',
                value: (row) => row.open_date,
            },
        },
    )
    assert.deepEqual(
        sortedByOpened.map((row) => row.symbol),
        ['ADA/USDT', 'BTC/USDT', 'ETH/USDT'],
    )
    assert.ok(resolveTradeSortTimestamp(rows[0].open_date) !== null)
})
