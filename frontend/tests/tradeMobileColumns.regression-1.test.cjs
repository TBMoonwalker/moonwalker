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
const openTradesSource = fs.readFileSync(
    path.join(rootDir, 'src/components/OpenTrades.vue'),
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
        'open_date',
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
    assert.match(openTradeColumnsSource, /if \(options\.isMobile\.value\)/)
    assert.match(openTradeColumnsSource, /key: 'stop'/)
    assert.match(openTradeColumnsSource, /options\.isMobile\.value\s*\?\s*\[sellAction, renderOverflowActions\(rowData\)\]/)
    assert.match(openTradeColumnsSource, /class: 'trade-action-label'/)
})

test('mobile trade ledger keeps action controls in a compact touch grid', () => {
    assert.match(tradesViewSource, /grid-template-columns: repeat\(2, 44px\);/)
    assert.match(tradesViewSource, /width: 92px;/)
    assert.match(tradesViewSource, /open-trades-table \.trade-row-actions/)
    assert.match(tradesViewSource, /grid-template-columns: 44px;/)
    assert.match(tradesViewSource, /width: 44px;/)
    assert.match(tradesViewSource, /min-width: 44px !important;/)
    assert.match(tradesViewSource, /grid-column: 1 \/ -1;/)
    assert.match(tradesViewSource, /open-trades-table \.trade-row-actions \.trade-action-more/)
    assert.match(tradesViewSource, /grid-column: auto;/)
    assert.match(tradesViewSource, /clip: rect\(0 0 0 0\);/)
})

test('mobile trade ledger reduces first column indentation', () => {
    assert.match(tradesViewSource, /data-col-key="__n_expand__"/)
    assert.match(tradesViewSource, /n-data-table-table colgroup col:first-child/)
    assert.match(openTradeColumnsSource, /OPEN_TRADES_MOBILE_COLUMN_WIDTHS/)
    assert.match(openTradeColumnsSource, /symbol: 104/)
    assert.match(openTradeColumnsSource, /display_profit_percent: 72/)
    assert.match(openTradeColumnsSource, /open_date: 85/)
    assert.match(openTradeColumnsSource, /action: 64/)
    assert.match(openTradeColumnsSource, /title: options\.isMobile\.value \? 'Open' : 'Opened'/)
    assert.doesNotMatch(openTradeColumnsSource, /return \[\.\.\.hiddenColumns, \.\.\.mobileColumns\]/)
    assert.match(openTradeColumnsSource, /return mobileColumns/)
    assert.match(openTradesSource, /class="open-trades-table"/)
    assert.match(tradesViewSource, /open-trades-table \.n-data-table-table colgroup col:nth-child\(1\)/)
    assert.match(tradesViewSource, /open-trades-table \.n-data-table-table colgroup col:nth-child\(2\)/)
    assert.match(tradesViewSource, /open-trades-table \.n-data-table-table colgroup col:nth-child\(3\)/)
    assert.match(tradesViewSource, /open-trades-table \.n-data-table-table colgroup col:nth-child\(4\)/)
    assert.doesNotMatch(tradesViewSource, /open-trades-table \.n-data-table-table colgroup col:nth-child\(5\)/)
    assert.match(tradesViewSource, /padding-left: 0 !important;/)
    assert.match(tradesViewSource, /min-width: 104px;/)
    assert.match(tradesViewSource, /max-width: 104px;/)
    assert.match(tradesViewSource, /min-width: 64px;/)
    assert.match(tradesViewSource, /max-width: 64px;/)
})

test('mobile trade ledger tabs avoid clipped horizontal scroll labels', () => {
    assert.match(tradesViewSource, /\.ledger-tabs :deep\(\.n-tabs-wrapper\)/)
    assert.match(tradesViewSource, /\.ledger-tabs :deep\(\.n-tabs-tab-wrapper\)/)
    assert.match(tradesViewSource, /isMobile \? 'Open' : 'Open Trades'/)
    assert.match(tradesViewSource, /isMobile \? 'Unsell\.' : 'Unsellable'/)
    assert.match(tradesViewSource, /isMobile \? 'Closed' : 'Closed Trades'/)
    assert.match(tradesViewSource, /\.ledger-tabs \.trade-tab-label/)
    assert.match(tradesViewSource, /text-overflow: ellipsis;/)
})

test('mobile closed trade delete action is compact and accessible', () => {
    const closedTradesSource = fs.readFileSync(
        path.join(rootDir, 'src/components/ClosedTrades.vue'),
        'utf8',
    )
    assert.match(closedTradesSource, /class="closed-trades-table"/)
    assert.match(closedTradesSource, /TrashBinOutline/)
    assert.match(closedTradesSource, /title: isMobile\.value \? '' : 'Action'/)
    assert.match(closedTradesSource, /'aria-label': `Delete \$\{rowData\.symbol\}`/)
    assert.match(closedTradesSource, /class: 'trade-row-actions trade-row-actions-delete'/)
    assert.match(tradesViewSource, /closed-trades-table \.n-data-table-th\[data-col-key="action"\]/)
    assert.match(tradesViewSource, /width: 52px;/)
})
