const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

const tradesViewSource = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'views', 'TradesView.vue'),
    'utf8',
)

test('performance range uses labelled native buttons with pressed state', () => {
    assert.match(tradesViewSource, /const performanceRange = ref<PerformanceRange>\('all'\)/)
    assert.match(tradesViewSource, /role="group" aria-label="Performance range"/)
    assert.match(tradesViewSource, /:aria-pressed="performanceRange === range\.value"/)
    assert.match(tradesViewSource, /<UpnlChart v-if="performanceRange === 'all'" :range="performanceRange" \/>/)
    assert.match(tradesViewSource, /<Charts v-else :key="performanceRange" :period="profitPeriod" \/>/)
    for (const [range, period] of [['1d', 'daily'], ['30d', 'monthly'], ['365d', 'yearly']]) {
        assert.ok(tradesViewSource.includes(`'${range}': '${period}'`))
    }
    for (const label of ['ALL', '1D', '30D', '1Y']) {
        assert.ok(tradesViewSource.includes(`label: '${label}'`))
    }
})

test('trade heading switches the three full-width ledgers', () => {
    assert.match(tradesViewSource, /role="group" aria-label="Trade records"/)
    for (const view of ['open', 'closed', 'unsellable']) {
        assert.ok(tradesViewSource.includes(`:aria-pressed="activeTradeView === '${view}'"`))
    }
    assert.match(tradesViewSource, /<OpenTrades v-if="activeTradeView === 'open'"/)
    assert.match(tradesViewSource, /<ClosedTrades v-else-if="activeTradeView === 'closed'"/)
    assert.match(tradesViewSource, /<UnsellableTrades v-else \/>/)
    assert.doesNotMatch(tradesViewSource, /<n-tabs/)
})
