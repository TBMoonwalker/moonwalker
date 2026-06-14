const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

const chartsSource = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'components', 'Charts.vue'),
    'utf8',
)
const tradesViewSource = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'views', 'TradesView.vue'),
    'utf8',
)
const appSource = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'App.vue'),
    'utf8',
)
const upnlStoreSource = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'stores', 'upnl.ts'),
    'utf8',
)
const profitStoreSource = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'stores', 'profit.ts'),
    'utf8',
)

test('daily monthly and yearly profit charts render a visible running average line', () => {
    assert.match(chartsSource, /BarChart,\s*LineChart/)
    assert.match(chartsSource, /const runningAverageProfit = profitValues\.map/)
    assert.match(chartsSource, /return cumulativeProfit \/ \(index \+ 1\)/)
    assert.match(chartsSource, /name:\s*'Running average'/)
    assert.match(chartsSource, /data:\s*runningAverageProfit/)
    assert.match(chartsSource, /type:\s*'dashed'/)
    assert.match(tradesViewSource, /<Charts v-if="activeProfitTab === 'daily-profit'" period="daily" \/>/)
    assert.match(tradesViewSource, /<Charts v-if="activeProfitTab === 'monthly-profit'" period="monthly" \/>/)
    assert.match(tradesViewSource, /<Charts v-if="activeProfitTab === 'yearly-profit'" period="yearly" \/>/)
})

test('profit charts stay mounted and reuse cached history across navigation', () => {
    assert.match(appSource, /<RouterView v-slot="\{ Component \}">/)
    assert.match(appSource, /<KeepAlive>/)
    assert.match(appSource, /<component :is="Component" \/>/)
    assert.match(upnlStoreSource, /UPNL_HISTORY_CACHE_TTL_MS/)
    assert.match(upnlStoreSource, /pendingLoad/)
    assert.match(upnlStoreSource, /hasFreshCache/)
    assert.match(profitStoreSource, /PROFIT_HISTORY_CACHE_TTL_MS/)
    assert.match(profitStoreSource, /pendingLoads/)
    assert.match(profitStoreSource, /dataByPeriod/)
    assert.match(profitStoreSource, /get_profit_history_data/)
})
