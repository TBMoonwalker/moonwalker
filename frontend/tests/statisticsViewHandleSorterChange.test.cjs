const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

const source = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'views', 'StatisticsView.vue'),
    'utf8',
)

// ---------------------------------------------------------------------------
// Functional mirror of handleSymbolSorterChange
// ---------------------------------------------------------------------------

let symbolSortState = { columnKey: 'trades', order: 'descend' }
let symbolPagination = { page: 1, pageSize: 10 }

function handleSymbolSorterChange(sorter) {
    if (sorter && sorter.order !== false) {
        symbolSortState = {
            columnKey: sorter.columnKey ?? sorter.key,
            order: sorter.order,
        }
    } else {
        symbolSortState = null
    }
    symbolPagination.page = 1
}

// Reset state before each test
function resetState() {
    symbolSortState = { columnKey: 'trades', order: 'descend' }
    symbolPagination = { page: 1, pageSize: 10 }
}

// ---------------------------------------------------------------------------
// sorter.columnKey undefined -- falls back to sorter.key
// ---------------------------------------------------------------------------

test('handleSymbolSorterChange uses sorter.key when columnKey is undefined', () => {
    resetState()
    // Naive UI sometimes provides `key` instead of `columnKey`
    handleSymbolSorterChange({ key: 'win_rate', order: 'ascend' })
    assert.equal(symbolSortState.columnKey, 'win_rate')
    assert.equal(symbolSortState.order, 'ascend')
})

test('handleSymbolSorterChange prefers columnKey over key when both present', () => {
    resetState()
    handleSymbolSorterChange({ columnKey: 'total_profit', key: 'win_rate', order: 'descend' })
    assert.equal(symbolSortState.columnKey, 'total_profit')
})

// ---------------------------------------------------------------------------
// sorter.order === false -- clears sort state
// ---------------------------------------------------------------------------

test('handleSymbolSorterChange sets sortState to null when order is false', () => {
    resetState()
    handleSymbolSorterChange({ columnKey: 'trades', order: false })
    assert.strictEqual(symbolSortState, null)
})

test('handleSymbolSorterChange sets sortState to null when sorter is null', () => {
    resetState()
    handleSymbolSorterChange(null)
    assert.strictEqual(symbolSortState, null)
})

test('handleSymbolSorterChange sets sortState to null when sorter is undefined', () => {
    resetState()
    handleSymbolSorterChange(undefined)
    assert.strictEqual(symbolSortState, null)
})

// ---------------------------------------------------------------------------
// Pagination always resets to page 1 on sort change
// ---------------------------------------------------------------------------

test('handleSymbolSorterChange resets page to 1 even when on page 3', () => {
    resetState()
    symbolPagination.page = 3
    handleSymbolSorterChange({ columnKey: 'avg_profit', order: 'ascend' })
    assert.equal(symbolPagination.page, 1)
})

test('handleSymbolSorterChange resets page to 1 when clearing sort', () => {
    resetState()
    symbolPagination.page = 2
    handleSymbolSorterChange(null)
    assert.equal(symbolPagination.page, 1)
})

// ---------------------------------------------------------------------------
// Source verification: the actual component has the fallback pattern
// ---------------------------------------------------------------------------

test('source handleSymbolSorterChange has columnKey ?? key fallback', () => {
    assert.match(
        source,
        /sorter\.columnKey \?\? sorter\.key/,
        'must have fallback from columnKey to key',
    )
})

test('source handleSymbolSorterChange checks sorter.order !== false', () => {
    assert.match(
        source,
        /sorter\.order !== false/,
        'must check for order === false to clear sort',
    )
})
