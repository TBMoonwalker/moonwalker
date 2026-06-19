const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

const openTradeColumnsSource = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'composables', 'useOpenTradeColumns.ts'),
    'utf8',
)

test('open trade TP/SO beam keeps price status separate from SO count', () => {
    // Regression: the design refresh changed the beam to SO-count progress only.
    // Trades with zero safety orders then rendered a grey-only TP/SO status.
    assert.ok(
        openTradeColumnsSource.includes('const avgPrice = Number(rowData.avg_price)') &&
            openTradeColumnsSource.includes('const tpPrice = Number(rowData.tp_price)') &&
            openTradeColumnsSource.includes('const currentPrice = Number(rowData.current_price)'),
        'expected the TP/SO beam to derive status from current, average, and take-profit prices',
    )
    assert.ok(
        openTradeColumnsSource.includes('currentPrice < avgPrice') &&
            openTradeColumnsSource.includes("? 'is-warning'") &&
            openTradeColumnsSource.includes(": 'is-active'"),
        'expected the TP/SO beam tone to show warning/active price status independently of SO count',
    )
    assert.ok(
        openTradeColumnsSource.includes('left: `${fillStart}%`') &&
            openTradeColumnsSource.includes('width: `${fillWidth}%`'),
        'expected the TP/SO beam fill to position the current-vs-average price span',
    )
    assert.ok(
        !openTradeColumnsSource.includes('safetyOrderCount <= 0') ||
            !openTradeColumnsSource.includes("? 'is-idle'"),
        'expected zero safety orders not to force the TP/SO beam into grey idle state',
    )
})
