const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

const { loadFrontendModule } = require('./helpers/loadFrontendModule.cjs')
const rootDir = path.resolve(__dirname, '..')
const openTradeColumnsSource = fs.readFileSync(
    path.join(rootDir, 'src/composables/useOpenTradeColumns.ts'),
    'utf8',
)
const tradesViewSource = fs.readFileSync(
    path.join(rootDir, 'src/views/TradesView.vue'),
    'utf8',
)

const {
    CLOSED_TRADES_MOBILE_COLUMN_KEYS,
    CLOSED_TRADES_TABLET_COLUMN_KEYS,
    OPEN_TRADES_MOBILE_COLUMN_KEYS,
    OPEN_TRADES_TABLET_COLUMN_KEYS,
    shouldShowTradeTableColumn,
} = loadFrontendModule('src/helpers/tradeTable.ts')

test('mobile open trades keeps PnL visible without the cost column', () => {
    assert.deepEqual(OPEN_TRADES_MOBILE_COLUMN_KEYS, [
        'symbol',
        'display_profit_percent',
        'action',
    ])
    assert.equal(
        shouldShowTradeTableColumn(
            'display_profit_percent',
            OPEN_TRADES_MOBILE_COLUMN_KEYS,
        ),
        true,
    )
    assert.equal(
        shouldShowTradeTableColumn('profit', OPEN_TRADES_MOBILE_COLUMN_KEYS),
        false,
    )
    assert.equal(
        shouldShowTradeTableColumn('cost', OPEN_TRADES_MOBILE_COLUMN_KEYS),
        false,
    )
})

test('tablet open trades keeps cost and PnL columns visible', () => {
    assert.deepEqual(OPEN_TRADES_TABLET_COLUMN_KEYS, [
        'symbol',
        'cost',
        'display_profit_percent',
        'action',
        'open_date',
    ])
})

test('mobile closed trades keeps PnL visible without the cost column', () => {
    assert.deepEqual(CLOSED_TRADES_MOBILE_COLUMN_KEYS, [
        'symbol',
        'profit',
        'profit_percent',
        'close_date',
        'action',
    ])
    assert.equal(
        shouldShowTradeTableColumn('cost', CLOSED_TRADES_MOBILE_COLUMN_KEYS),
        false,
    )
})

test('tablet closed trades keeps cost and PnL columns visible', () => {
    assert.deepEqual(CLOSED_TRADES_TABLET_COLUMN_KEYS, [
        'symbol',
        'amount',
        'profit',
        'cost',
        'profit_percent',
        'close_reason',
        'so_count',
        'close_date',
        'action',
    ])
})

test('mobile open trade actions expose icon buttons with accessible labels', () => {
    assert.match(openTradeColumnsSource, /class: 'trade-action-button trade-action-sell'/)
    assert.match(openTradeColumnsSource, /'aria-label': `Sell \$\{rowData\.symbol\}`/)
    assert.match(openTradeColumnsSource, /class: 'trade-action-button trade-action-stop'/)
    assert.match(openTradeColumnsSource, /'aria-label': `Stop \$\{rowData\.symbol\}`/)
    assert.match(openTradeColumnsSource, /class: 'trade-action-label'/)
})

test('mobile trade ledger keeps action controls in a compact touch grid', () => {
    assert.match(tradesViewSource, /grid-template-columns: repeat\(2, 44px\);/)
    assert.match(tradesViewSource, /width: 92px;/)
    assert.match(tradesViewSource, /min-width: 44px !important;/)
    assert.match(tradesViewSource, /grid-column: 1 \/ -1;/)
    assert.match(tradesViewSource, /clip: rect\(0 0 0 0\);/)
})
