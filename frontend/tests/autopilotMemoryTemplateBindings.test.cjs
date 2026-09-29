const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

const pageSource = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'views', 'AutopilotMemoryView.vue'),
    'utf8',
)
const statisticsSource = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'components', 'Statistics.vue'),
    'utf8',
)
const tradesViewSource = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'views', 'TradesView.vue'),
    'utf8',
)
const headerSource = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'components', 'AppHeader.vue'),
    'utf8',
)

test('main dashboard Autopilot navigation uses an explicit action', () => {
    assert.match(tradesViewSource, /<div class="status-autopilot">/)
    assert.match(tradesViewSource, /:to="\{ name: 'controlCenterAutopilot' \}"/)
    assert.match(tradesViewSource, />\s*Open Autopilot ↗\s*<\/RouterLink>/)
    assert.doesNotMatch(tradesViewSource, /class="stat-cell autopilot-cell autopilot-link"/)
    assert.doesNotMatch(tradesViewSource, /role="link"/)
    assert.doesNotMatch(tradesViewSource, /tabindex="0"/)
    assert.doesNotMatch(tradesViewSource, /@click="openAutopilotPage"/)
    assert.doesNotMatch(tradesViewSource, /router\.push\(\{ name: 'controlCenterAutopilot' \}\)/)
})

test('main dashboard exposure shows tradable funds with exchange context', () => {
    assert.match(statisticsSource, /funds_tradable/)
    assert.match(statisticsSource, /capital_available_quote/)
    assert.match(statisticsSource, /Portfolio value/)
    assert.match(statisticsSource, /Net profit &amp; loss/)
    assert.match(statisticsSource, /Funds in deals/)
    assert.match(statisticsSource, /Available to trade/)
    assert.match(statisticsSource, /Exchange free/)
    assert.match(statisticsSource, /exposure-reserved/)
    assert.match(statisticsSource, /exposure-unallocated/)
    assert.match(statisticsSource, /capital_effective_max_fund/)
    assert.match(statisticsSource, /exposure-tradable/)
})

test('full Autopilot page stays read-only and links to its configuration', () => {
    assert.match(pageSource, /Trading overview/)
    assert.match(pageSource, /Configure Autopilot/)
    assert.match(pageSource, /Latest Autopilot moves/)
    assert.match(pageSource, /splitTradeSymbol/)
    assert.match(pageSource, /formatTrustBoardSymbol\(row\.symbol\)/)
    assert.match(pageSource, /trust-row-symbol/)
    assert.match(pageSource, /background:\s*rgba\(46,\s*125,\s*91,\s*0\.08\)/)
    assert.match(pageSource, /trust-row-positive \.trust-row-meta/)
    assert.doesNotMatch(pageSource, /n-form/i)
})

test('sidebar navigation separates configuration and utilities', () => {
    assert.match(headerSource, /label: 'Configuration'/)
    assert.match(headerSource, /label: 'Strategy Builder'/)
    assert.match(headerSource, /label: 'Utilities'/)
    assert.equal((headerSource.match(/label:\s*'Monitoring'/g) ?? []).length, 1)
})
