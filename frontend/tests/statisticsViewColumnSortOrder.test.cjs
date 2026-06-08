const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

const source = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'views', 'StatisticsView.vue'),
    'utf8',
)

// ---------------------------------------------------------------------------
// Functional mirror of columnSortOrder
// ---------------------------------------------------------------------------

function columnSortOrder(symbolSortState, key) {
    return symbolSortState?.columnKey === key
        ? symbolSortState.order
        : null
}

// ---------------------------------------------------------------------------
// Matching key returns the current order
// ---------------------------------------------------------------------------

test('columnSortOrder returns ascend when key matches and order is ascend', () => {
    assert.equal(
        columnSortOrder({ columnKey: 'trades', order: 'ascend' }, 'trades'),
        'ascend',
    )
})

test('columnSortOrder returns descend when key matches and order is descend', () => {
    assert.equal(
        columnSortOrder({ columnKey: 'win_rate', order: 'descend' }, 'win_rate'),
        'descend',
    )
})

// ---------------------------------------------------------------------------
// Non-matching key returns null
// ---------------------------------------------------------------------------

test('columnSortOrder returns null when key does not match', () => {
    assert.strictEqual(
        columnSortOrder({ columnKey: 'trades', order: 'descend' }, 'win_rate'),
        null,
    )
})

// ---------------------------------------------------------------------------
// Null sort state returns null for any key
// ---------------------------------------------------------------------------

test('columnSortOrder returns null when sortState is null', () => {
    assert.strictEqual(columnSortOrder(null, 'trades'), null)
    assert.strictEqual(columnSortOrder(null, 'win_rate'), null)
})

test('columnSortOrder returns null when sortState is undefined', () => {
    assert.strictEqual(columnSortOrder(undefined, 'trades'), null)
})

// ---------------------------------------------------------------------------
// Source verification
// ---------------------------------------------------------------------------

test('source columnSortOrder function exists with correct signature', () => {
    assert.match(source, /function columnSortOrder\(key: string\)/)
})

test('source columnSortOrder uses optional chaining on symbolSortState', () => {
    assert.match(source, /symbolSortState\.value\?\.columnKey/)
})
