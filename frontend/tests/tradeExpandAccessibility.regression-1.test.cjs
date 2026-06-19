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

test('trade replay expansion is available from the whole row', () => {
    // Regression: visible arrow-only expanders added noise and a tiny hit target.
    // Found by /qa on 2026-06-08.
    // Report: .gstack/qa-reports/qa-report-localhost-8130-2026-06-08.md
    assert.ok(
        openTradeColumnsSource.includes("type: 'expand'") &&
            closedTradesSource.includes("type: 'expand'") &&
            openTradeColumnsSource.includes('trade-hidden-expand-cell') &&
            closedTradesSource.includes('trade-hidden-expand-cell'),
        'expected open and closed trade tables to keep hidden expansion renderers',
    )
    assert.ok(
        openTradesSource.includes('v-model:expanded-row-keys="expandedTradeRowKeys"') &&
            closedTradesSource.includes('v-model:expanded-row-keys="expandedClosedTradeRowKeys"') &&
            openTradesSource.includes(':row-props="getOpenTradeRowProps"') &&
            closedTradesSource.includes(':row-props="getClosedTradeRowProps"'),
        'expected open and closed trade expansion to be controlled by row props',
    )
    assert.ok(
        openTradesSource.includes("'aria-expanded': expandedTradeRowKeys.value.includes(rowKey)") &&
            closedTradesSource.includes("'aria-expanded': expandedClosedTradeRowKeys.value.includes(rowKey)") &&
            openTradesSource.includes("'aria-label': `Toggle trade details for ${rowData.symbol}`") &&
            closedTradesSource.includes("'aria-label': `Toggle trade details for ${rowData.symbol}`"),
        'expected keyboard-focusable trade rows to expose their expanded state',
    )
    assert.ok(
        !openTradeColumnsSource.includes('RenderExpandIcon') &&
            !closedTradesSource.includes('RenderExpandIcon') &&
            !openTradeColumnsSource.includes('trade-expand-button') &&
            !closedTradesSource.includes('trade-expand-button'),
        'expected visible arrow expand buttons to be removed from trade rows',
    )
    assert.ok(
        openTradesSource.includes('.n-data-table-table colgroup col:first-child') &&
            closedTradesSource.includes('.n-data-table-table colgroup col:first-child') &&
            openTradesSource.includes('display: none;') &&
            closedTradesSource.includes('display: none;'),
        'expected the internal expand column to collapse without leaving a left gutter',
    )
})
