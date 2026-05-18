const assert = require('node:assert/strict')
const test = require('node:test')

const { loadFrontendModule } = require('./helpers/loadFrontendModule.cjs')

const {
    CLOSED_TRADES_MOBILE_COLUMN_KEYS,
    CLOSED_TRADES_TABLET_COLUMN_KEYS,
    OPEN_TRADES_MOBILE_COLUMN_KEYS,
    OPEN_TRADES_TABLET_COLUMN_KEYS,
    shouldShowTradeTableColumn,
} = loadFrontendModule('src/helpers/tradeTable.ts')

test('mobile open trades keeps cost and PnL columns visible', () => {
    assert.deepEqual(OPEN_TRADES_MOBILE_COLUMN_KEYS, [
        'symbol',
        'cost',
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

test('mobile closed trades keeps cost and PnL columns visible', () => {
    assert.deepEqual(CLOSED_TRADES_MOBILE_COLUMN_KEYS, [
        'symbol',
        'profit',
        'cost',
        'profit_percent',
        'close_date',
        'action',
    ])
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
