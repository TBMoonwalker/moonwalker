const assert = require('node:assert/strict')
const test = require('node:test')

process.env.TZ = 'Europe/Vienna'

const { loadFrontendModule } = require('./helpers/loadFrontendModule.cjs')

const { resolveTradeDateTime } = loadFrontendModule('src/helpers/tradeTable.ts')

test('timezone-less backend trade dates keep their saved wall time', () => {
    assert.deepEqual(resolveTradeDateTime('2026-04-26 21:57:41'), {
        date: '26 Apr 26',
        time: '21:57',
    })
})

test('timezone-explicit backend trade dates render as the local instant', () => {
    assert.deepEqual(resolveTradeDateTime('2026-04-26 19:57:41+00:00'), {
        date: '26 Apr 26',
        time: '21:57',
    })
})
