const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

const rootDir = path.resolve(__dirname, '..')
const mainCssSource = fs.readFileSync(
    path.join(rootDir, 'src/assets/main.css'),
    'utf8',
)
const tradesViewSource = fs.readFileSync(
    path.join(rootDir, 'src/views/TradesView.vue'),
    'utf8',
)
const statisticsViewSource = fs.readFileSync(
    path.join(rootDir, 'src/views/StatisticsView.vue'),
    'utf8',
)
const backtestViewSource = fs.readFileSync(
    path.join(rootDir, 'src/views/BacktestView.vue'),
    'utf8',
)
const controlCenterViewSource = fs.readFileSync(
    path.join(rootDir, 'src/views/ControlCenterView.vue'),
    'utf8',
)
const configViewSource = fs.readFileSync(
    path.join(rootDir, 'src/views/ConfigView.vue'),
    'utf8',
)
const monitoringViewSource = fs.readFileSync(
    path.join(rootDir, 'src/views/MonitoringView.vue'),
    'utf8',
)
const autopilotMemoryViewSource = fs.readFileSync(
    path.join(rootDir, 'src/views/AutopilotMemoryView.vue'),
    'utf8',
)

test('operator pages share the trades-page shell blueprint', () => {
    for (const token of [
        '.operator-console-page',
        '.dashboard-panel',
        '.admission-strip',
        '.calm-tabs',
        '.ledger-panel',
        '.operator-card',
        '.operator-subpanel',
    ]) {
        assert.ok(
            mainCssSource.includes(token),
            `expected shared operator blueprint CSS to define ${token}`,
        )
    }

    for (const [name, source] of [
        ['trades', tradesViewSource],
        ['statistics', statisticsViewSource],
        ['backtest', backtestViewSource],
        ['control center', controlCenterViewSource],
        ['config', configViewSource],
        ['monitoring', monitoringViewSource],
        ['autopilot memory', autopilotMemoryViewSource],
    ]) {
        assert.ok(
            source.includes('operator-console-page'),
            `expected ${name} to use the shared operator page shell`,
        )
    }
})

test('operator views do not reintroduce legacy page shells', () => {
    const legacyTokens = [
        'mw-shell-card',
        'mw-muted-card',
        'settings-intro-card',
        'monitoring-intro-card',
        'stats-intro-card',
        'backtest-hero',
        'hero-insight',
        'page-title',
    ]

    for (const [name, source] of [
        ['trades', tradesViewSource],
        ['statistics', statisticsViewSource],
        ['backtest', backtestViewSource],
        ['control center', controlCenterViewSource],
        ['config', configViewSource],
        ['monitoring', monitoringViewSource],
        ['autopilot memory', autopilotMemoryViewSource],
    ]) {
        for (const token of legacyTokens) {
            assert.ok(
                !source.includes(token),
                `expected ${name} to avoid legacy operator layout token ${token}`,
            )
        }
    }
})

test('secondary operator pages reuse panel tabs and ledger table rhythm', () => {
    assert.ok(
        statisticsViewSource.includes('dashboard-panel ledger-panel') &&
            statisticsViewSource.includes('class="calm-tabs statistics-tabs"'),
        'expected Statistics to use shared ledger panels and calm tabs',
    )
    assert.ok(
        backtestViewSource.includes('dashboard-panel ledger-panel chart-panel') &&
            backtestViewSource.includes('class="calm-tabs backtest-result-tabs"') &&
            !backtestViewSource.includes('class="backtest-hero'),
        'expected Backtest to use the Trades-style panels instead of a standalone hero',
    )
    assert.ok(
        controlCenterViewSource.includes('operator-console-page'),
        'expected Control Center to use the shared operator page shell',
    )
    assert.ok(
        monitoringViewSource.includes('operator-console-page') &&
            configViewSource.includes('operator-console-page') &&
            autopilotMemoryViewSource.includes('operator-console-page'),
        'expected legacy utility views to use the shared operator page shell',
    )
})
