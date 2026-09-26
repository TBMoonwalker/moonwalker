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
    // Charts render bare: the pane-level display-directive="show" (guarded below)
    // keeps them mounted, so a child v-show is redundant and asserted absent here.
    assert.match(tradesViewSource, /<UpnlChart\s*\/>/)
    assert.match(tradesViewSource, /<Charts period="daily" \/>/)
    assert.match(tradesViewSource, /<Charts period="monthly" \/>/)
    assert.match(tradesViewSource, /<Charts period="yearly" \/>/)
    // Keep-alive: naive-ui 2.45.3 reads display-directive from EACH <n-tab-pane>,
    // NOT from <n-tabs> (a value placed on <n-tabs> is a no-op), so every profit pane
    // must carry display-directive="show" — that keeps each chart
    // mounted, so a switch is a pure show/hide with no remount, re-animate, or refetch.
    // The count guards against regressing to a single <n-tabs> no-op or a dropped
    // directive (the earlier /display-directive="show"/ presence check was too weak).
    const panelShowCount = (tradesViewSource.match(/display-directive="show"/g) || []).length
    assert.ok(panelShowCount >= 4, 'each profit n-tab-pane must set display-directive="show" (found ' + panelShowCount + ')')
    for (const period of ['profit-overall', 'daily-profit', 'monthly-profit', 'yearly-profit']) {
      const tab = "getProfitTabProps('" + period + "')"
      const fromIdx = tradesViewSource.indexOf(tab)
      assert.ok(fromIdx >= 0, "tab-props for " + period + " is present")
      // display-directive must live on this pane's opening tag, not on the parent <n-tabs>
      const win = tradesViewSource.slice(fromIdx, fromIdx + 160)
      assert.ok(win.includes('display-directive="show"'), "pane " + period + " must enable display-directive on its own n-tab-pane")
    }
})

test('profit charts stay mounted and reuse cached history across navigation', () => {
    assert.match(appSource, /<RouterView v-slot="\{ Component, route \}">/)
    assert.match(appSource, /<KeepAlive v-else>/)
    assert.match(appSource, /<component :is="Component" \/>/)
    assert.match(upnlStoreSource, /UPNL_HISTORY_CACHE_TTL_MS/)
    assert.match(upnlStoreSource, /pendingLoad/)
    assert.match(upnlStoreSource, /hasFreshCache/)
    assert.match(profitStoreSource, /PROFIT_HISTORY_CACHE_TTL_MS/)
    assert.match(profitStoreSource, /pendingLoads/)
    assert.match(profitStoreSource, /dataByPeriod/)
    assert.match(profitStoreSource, /get_profit_history_data/)
})

test('control center unmounts so hidden listeners and pollers cannot stay active', () => {
    assert.match(appSource, /v-if="route\.name === 'controlCenter'"/)
    assert.match(appSource, /<KeepAlive v-else>/)
})
