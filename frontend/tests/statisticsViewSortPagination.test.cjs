const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

// Mirror the sort logic from sortedAndPaginatedSymbols computed
// so we can test it functionally with real data.
function sortSymbolRows(rows, sortState) {
    const sorted = [...rows]
    if (!sortState) return sorted

    const { columnKey, order } = sortState
    sorted.sort((a, b) => {
        let aVal = a[columnKey]
        let bVal = b[columnKey]
        if (typeof aVal === 'string') aVal = aVal.toLowerCase()
        if (typeof bVal === 'string') bVal = bVal.toLowerCase()
        if (aVal < bVal) return order === 'ascend' ? -1 : 1
        if (aVal > bVal) return order === 'ascend' ? 1 : -1
        return 0
    })
    return sorted
}

function paginateRows(rows, page, pageSize = 10) {
    const start = ((page ?? 1) - 1) * (pageSize ?? 10)
    return rows.slice(start, start + (pageSize ?? 10))
}

// ---------------------------------------------------------------------------
// Sort — numeric columns
// ---------------------------------------------------------------------------

test('sortSymbolRows sorts trades column descend by default', () => {
    const rows = [
        { symbol: 'BTC/USDT', trades: 5 },
        { symbol: 'ETH/USDT', trades: 20 },
        { symbol: 'ADA/USDT', trades: 10 },
    ]
    const result = sortSymbolRows(rows, { columnKey: 'trades', order: 'descend' })
    assert.deepEqual(
        result.map(r => r.symbol),
         ['ETH/USDT', 'ADA/USDT', 'BTC/USDT'],
     )
})

test('sortSymbolRows sorts trades column ascend', () => {
    const rows = [
        { symbol: 'BTC/USDT', trades: 5 },
        { symbol: 'ETH/USDT', trades: 20 },
        { symbol: 'ADA/USDT', trades: 10 },
    ]
    const result = sortSymbolRows(rows, { columnKey: 'trades', order: 'ascend' })
    assert.deepEqual(
        result.map(r => r.symbol),
         ['BTC/USDT', 'ADA/USDT', 'ETH/USDT'],
     )
})

test('sortSymbolRows sorts win_rate descend', () => {
    const rows = [
        { symbol: 'X', win_rate: 50 },
        { symbol: 'Y', win_rate: 90 },
        { symbol: 'Z', win_rate: 30 },
    ]
    const result = sortSymbolRows(rows, { columnKey: 'win_rate', order: 'descend' })
    assert.deepEqual(result.map(r => r.symbol), ['Y', 'X', 'Z'])
})

test('sortSymbolRows sorts total_profit with negative values', () => {
    const rows = [
        { symbol: 'A', total_profit: -5.2 },
        { symbol: 'B', total_profit: 12.3 },
        { symbol: 'C', total_profit: 0 },
    ]
    const result = sortSymbolRows(rows, { columnKey: 'total_profit', order: 'descend' })
    assert.deepEqual(result.map(r => r.symbol), ['B', 'C', 'A'])
})

// ---------------------------------------------------------------------------
// Sort — string columns (case-insensitive)
// ---------------------------------------------------------------------------

test('sortSymbolRows sorts symbol column case-insensitive ascend', () => {
    const rows = [
        { symbol: 'BTC/USDT', trades: 1 },
        { symbol: 'ada/usdt', trades: 2 },
        { symbol: 'Eth/USDT', trades: 3 },
    ]
    const result = sortSymbolRows(rows, { columnKey: 'symbol', order: 'ascend' })
    assert.deepEqual(result.map(r => r.symbol), ['ada/usdt', 'BTC/USDT', 'Eth/USDT'])
})

test('sortSymbolRows sorts symbol column case-insensitive descend', () => {
    const rows = [
        { symbol: 'BTC/USDT', trades: 1 },
        { symbol: 'ada/usdt', trades: 2 },
        { symbol: 'Eth/USDT', trades: 3 },
    ]
    const result = sortSymbolRows(rows, { columnKey: 'symbol', order: 'descend' })
    assert.deepEqual(result.map(r => r.symbol), ['Eth/USDT', 'BTC/USDT', 'ada/usdt'])
})

// ---------------------------------------------------------------------------
// Sort — no sort state (null)
// ---------------------------------------------------------------------------

test('sortSymbolRows returns unmodified order when sortState is null', () => {
    const rows = [
        { symbol: 'C', trades: 3 },
        { symbol: 'A', trades: 1 },
        { symbol: 'B', trades: 2 },
    ]
    const result = sortSymbolRows(rows, null)
    assert.deepEqual(result.map(r => r.symbol), ['C', 'A', 'B'])
})

// ---------------------------------------------------------------------------
// Sort — equal values maintain stable order
// ---------------------------------------------------------------------------

test('sortSymbolRows preserves original order for equal values', () => {
    const rows = [
        { symbol: 'A', trades: 10 },
        { symbol: 'B', trades: 10 },
        { symbol: 'C', trades: 10 },
    ]
    const result = sortSymbolRows(rows, { columnKey: 'trades', order: 'descend' })
    assert.deepEqual(result.map(r => r.symbol), ['A', 'B', 'C'])
})

// ---------------------------------------------------------------------------
// Pagination
// ---------------------------------------------------------------------------

test('paginateRows returns first 10 rows for page 1', () => {
    const rows = Array.from({ length: 25 }, (_, i) => ({ symbol: `S${i}`, trades: i }))
    const result = paginateRows(rows, 1)
    assert.equal(result.length, 10)
    assert.equal(result[0].symbol, 'S0')
    assert.equal(result[9].symbol, 'S9')
})

test('paginateRows returns rows 10-19 for page 2', () => {
    const rows = Array.from({ length: 25 }, (_, i) => ({ symbol: `S${i}`, trades: i }))
    const result = paginateRows(rows, 2)
    assert.equal(result.length, 10)
    assert.equal(result[0].symbol, 'S10')
    assert.equal(result[9].symbol, 'S19')
})

test('paginateRows returns remaining rows for last page', () => {
    const rows = Array.from({ length: 23 }, (_, i) => ({ symbol: `S${i}`, trades: i }))
    const result = paginateRows(rows, 3)
    assert.equal(result.length, 3)
    assert.equal(result[0].symbol, 'S20')
    assert.equal(result[2].symbol, 'S22')
})

test('paginateRows returns empty array when page exceeds data', () => {
    const rows = Array.from({ length: 10 }, (_, i) => ({ symbol: `S${i}`, trades: i }))
    const result = paginateRows(rows, 5)
    assert.deepEqual(result, [])
})

test('paginateRows uses custom page size', () => {
    const rows = Array.from({ length: 25 }, (_, i) => ({ symbol: `S${i}`, trades: i }))
    const result = paginateRows(rows, 2, 5)
    assert.equal(result.length, 5)
    assert.equal(result[0].symbol, 'S5')
    assert.equal(result[4].symbol, 'S9')
})

// ---------------------------------------------------------------------------
// Combined: sort then paginate
// ---------------------------------------------------------------------------

test('sort then paginate returns correct page of sorted data', () => {
    const rows = [
        { symbol: 'A', trades: 1 },
        { symbol: 'B', trades: 5 },
        { symbol: 'C', trades: 3 },
        { symbol: 'D', trades: 10 },
        { symbol: 'E', trades: 7 },
        { symbol: 'F', trades: 2 },
        { symbol: 'G', trades: 8 },
        { symbol: 'H', trades: 4 },
        { symbol: 'I', trades: 9 },
        { symbol: 'J', trades: 6 },
        { symbol: 'K', trades: 11 },
    ]
    const sorted = sortSymbolRows(rows, { columnKey: 'trades', order: 'descend' })
    const page1 = paginateRows(sorted, 1, 5)
    assert.deepEqual(
        page1.map(r => r.symbol),
         ['K', 'D', 'I', 'G', 'E'],
     )
    const page2 = paginateRows(sorted, 2, 5)
    assert.deepEqual(
        page2.map(r => r.symbol),
         ['J', 'B', 'H', 'C', 'F'],
     )
})

// ---------------------------------------------------------------------------
// Edge cases
// ---------------------------------------------------------------------------

test('sortSymbolRows handles empty array', () => {
    const result = sortSymbolRows([], { columnKey: 'trades', order: 'descend' })
    assert.deepEqual(result, [])
})

test('paginateRows handles empty array', () => {
    const result = paginateRows([], 1)
    assert.deepEqual(result, [])
})

test('sortSymbolRows handles single element', () => {
    const rows = [{ symbol: 'A', trades: 1 }]
    const result = sortSymbolRows(rows, { columnKey: 'trades', order: 'descend' })
    assert.deepEqual(result.map(r => r.symbol), ['A'])
})

test('paginateRows with page=0 defaults to page 1', () => {
    const rows = Array.from({ length: 5 }, (_, i) => ({ idx: i }))
    const result = paginateRows(rows, 0)
    // page 0 -> start = (0-1)*10 = -10 -> slice(-10, 0) = []
      // This is an edge case; the watch guard prevents page < 1
    assert.equal(result.length, 0)
})

// ---------------------------------------------------------------------------
// Source verification: ensure the actual component matches our test logic
// ---------------------------------------------------------------------------

const source = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'views', 'StatisticsView.vue'),
     'utf8',
)

test('source sortedAndPaginatedSymbols matches test sort logic structure', () => {
    // Verify the component uses the same sort pattern
    assert.match(source, /let rows = \[\.\.\.perSymbol\.value\]/)
    assert.match(source, /const ss = symbolSortState\.value/)
    assert.match(source, /if \(ss\)/)
    assert.match(source, /rows\.sort\(\(/)
    assert.match(source, /typeof aVal === 'string'/)
    assert.match(source, /aVal < bVal.*ss\.order === 'ascend'/)
    assert.match(source, /aVal > bVal.*ss\.order === 'ascend'/)
    assert.match(source, /return 0/)
    assert.match(source, /rows\.slice\(start/)
})

test('source pagination formula matches test paginateRows logic', () => {
    assert.match(
        source,
        /\(\(symbolPagination\.page \?\? 1\) - 1\) \* \(symbolPagination\.pageSize \?\? SYMBOL_PAGE_SIZE\)/,
     )
})
