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
const openTradeExpandedRowSource = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'components', 'OpenTradeExpandedRow.vue'),
    'utf8',
)
const tradeReplayChartSource = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'components', 'TradeReplayChart.vue'),
    'utf8',
)
const mainCssSource = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'assets', 'main.css'),
    'utf8',
)
const tradesViewSource = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'views', 'TradesView.vue'),
    'utf8',
)

function extractHiddenExpandCellBlock(source) {
    const match = source.match(
        /:deep\(\.trade-hidden-expand-cell\),\n:deep\(\.n-data-table-td--expand\) \{[^}]+\}/,
    )
    return match ? match[0] : ''
}

function hasExpandedDetailInset(source) {
    return /n-data-table-tr--expanded:not\(\.trade-row-clickable\)[^{]+>\s*\.n-data-table-td\[colspan\][^{]*\{\s*padding-inline: 12px;/s.test(
        source,
    )
}

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
            openTradesSource.includes('width: 0 !important') &&
            closedTradesSource.includes('width: 0 !important'),
        'expected the internal expand column to stay zero-width without leaving a left gutter',
    )
    assert.ok(
        !extractHiddenExpandCellBlock(openTradesSource).includes('display: none') &&
            !extractHiddenExpandCellBlock(closedTradesSource).includes('display: none'),
        'expected the hidden expand table cell to remain in table flow so data cells keep their columns',
    )
})

test('expanded open trade layout stays stable and stretches replay chart', () => {
    assert.ok(
        openTradesSource.includes(':deep(.n-data-table-table)') &&
            openTradesSource.includes('table-layout: fixed') &&
            openTradesSource.includes('width: 100%'),
        'expected open trade rows to keep column spacing stable when expansion mounts',
    )
    assert.ok(
        openTradeExpandedRowSource.includes('flex-wrap: nowrap') &&
            openTradeExpandedRowSource.includes('align-self: stretch') &&
            openTradeExpandedRowSource.includes('flex: 1 1 0'),
        'expected the open-trade replay column to stretch beside taller order timelines',
    )
    assert.ok(
        tradeReplayChartSource.includes('.expand-chart-card :deep(.n-card__content)') &&
            tradeReplayChartSource.includes('flex: 1 1 auto') &&
            tradeReplayChartSource.includes('flex: 1 1 400px') &&
            tradeReplayChartSource.includes('min-height: 400px'),
        'expected the TradingView replay chart stack to fill the expanded row height',
    )
})

test('expanded ledger padding applies only to the detail row cell', () => {
    assert.ok(
        mainCssSource.includes(
            '.n-data-table-tr--expanded:not(.trade-row-clickable)',
        ),
        'expected global ledger spacing to exclude the clicked data row',
    )
    assert.ok(
        !mainCssSource.includes(
            '.ledger-panel .n-data-table-tr--expanded > .n-data-table-td {\n',
        ),
        'expected expanded data rows to keep their normal cell padding',
    )
    assert.ok(
        tradesViewSource.includes(
            ':deep(.n-data-table-tr--expanded:not(.trade-row-clickable) > .n-data-table-td[colspan])',
        ),
        'expected the trades page detail row spacing to exclude clicked data rows',
    )
    assert.ok(
        hasExpandedDetailInset(mainCssSource) &&
            tradesViewSource.includes(
                ':deep(.n-data-table-tr--expanded:not(.trade-row-clickable) > .n-data-table-td[colspan]) {\n  padding-inline: 12px;',
            ),
        'expected the expanded detail row content to align with normal table cell insets',
    )
    assert.ok(
        !tradesViewSource.includes(
            ':deep(.n-data-table-tr--expanded > .n-data-table-td) {\n',
        ),
        'expected expanded trade rows to keep their normal cell padding',
    )
})
