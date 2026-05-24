const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

const backtestViewSource = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'views', 'BacktestView.vue'),
    'utf8',
)
const backtestChartSource = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'components', 'BacktestResultChart.vue'),
    'utf8',
)
const appHeaderSource = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'components', 'AppHeader.vue'),
    'utf8',
)

test('backtest view is wired to the backend replay endpoint and chart markers', () => {
    assert.ok(
        backtestViewSource.includes("fetchJson<BacktestResult>('/backtest/run'"),
        'expected the Backtest UI to call the backend replay endpoint',
    )
    assert.ok(
        backtestViewSource.includes('previousResult'),
        'expected the Backtest UI to keep a previous run for comparison',
    )
    assert.ok(
        backtestViewSource.includes('tradeModeOptions'),
        'expected the Backtest UI to expose trade mode selection',
    )
    assert.ok(
        backtestViewSource.includes('sidestepBearishStrategySlug'),
        'expected the Backtest UI to configure sidestep strategies',
    )
    assert.ok(
        backtestViewSource.includes("fetchJson<ConfigSnapshotResponse>('/config/all')"),
        'expected the Backtest UI to load configured quote currency',
    )
    assert.ok(
        backtestViewSource.includes('/data/exchange/symbols/'),
        'expected the Backtest UI to load symbols from the exchange',
    )
    assert.ok(
        backtestViewSource.includes('v-if="!isSidestepMode" class="control-grid two"'),
        'expected sidestep mode to hide dynamic DCA safety-order controls',
    )
    assert.ok(
        backtestChartSource.includes('createSeriesMarkers'),
        'expected the Backtest chart to render buy and sell markers',
    )
    assert.ok(
        appHeaderSource.includes("label: 'Backtest'"),
        'expected the app header to expose the Backtest route',
    )
})
