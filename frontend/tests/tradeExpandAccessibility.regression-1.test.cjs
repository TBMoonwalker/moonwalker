const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

const openTradeColumnsSource = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'composables', 'useOpenTradeColumns.ts'),
    'utf8',
)
const openTradesSource = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'components', 'OpenTrades.vue'),
    'utf8',
)
const closedTradesSource = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'components', 'ClosedTrades.vue'),
    'utf8',
)

test('trade replay expand controls expose accessible labels', () => {
    // Regression: ISSUE-001 - row replay expanders were cursor-only icons.
    // Found by /qa on 2026-06-08.
    // Report: .gstack/qa-reports/qa-report-localhost-8130-2026-06-08.md
    assert.ok(
        openTradeColumnsSource.includes('type RenderExpandIcon') &&
            closedTradesSource.includes('type RenderExpandIcon'),
        'expected open and closed trade tables to type their custom expand icon renderer',
    )
    assert.ok(
        openTradeColumnsSource.includes("'aria-label': `${") &&
            closedTradesSource.includes("'aria-label': `${") &&
            openTradeColumnsSource.includes("} trade details for ${symbol}`") &&
            closedTradesSource.includes("} trade details for ${symbol}`"),
        'expected open and closed trade expand controls to expose stateful accessible labels',
    )
    assert.ok(
        openTradeColumnsSource.includes("class: 'trade-expand-button'") &&
            closedTradesSource.includes("class: 'trade-expand-button'") &&
            openTradesSource.includes('.trade-expand-button') &&
            closedTradesSource.includes('.trade-expand-button'),
        'expected labelled expand buttons to keep a stable compact table footprint',
    )
})
