const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

const source = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'views', 'StatisticsView.vue'),
    'utf8',
)

// ---------------------------------------------------------------------------
// Functional mirror of the syncPaginationBounds page correction logic
// ---------------------------------------------------------------------------

const SYMBOL_PAGE_SIZE = 10

function syncPaginationBounds(pagination, itemCount) {
    const pageSize = pagination.pageSize ?? SYMBOL_PAGE_SIZE
    pagination.itemCount = itemCount
    const maxPage = Math.max(1, Math.ceil(itemCount / pageSize))
    if ((pagination.page ?? 1) > maxPage) {
        pagination.page = maxPage
    }
    return { itemCount, maxPage, correctedPage: pagination.page ?? 1 }
}

// ---------------------------------------------------------------------------
// Normal data -- page stays the same
// ---------------------------------------------------------------------------

test('watch keeps page 1 when data has 25 rows', () => {
    const result = syncPaginationBounds({ page: 1, pageSize: 10 }, 25)
    assert.equal(result.itemCount, 25)
    assert.equal(result.maxPage, 3)
    assert.equal(result.correctedPage, 1)
})

test('watch keeps page 3 when data has 30 rows', () => {
    const result = syncPaginationBounds({ page: 3, pageSize: 10 }, 30)
    assert.equal(result.maxPage, 3)
    assert.equal(result.correctedPage, 3)
})

// ---------------------------------------------------------------------------
// Data shrinks -- page is corrected downward
// ---------------------------------------------------------------------------

test('watch corrects page from 3 to 1 when data shrinks to 5 rows', () => {
    const result = syncPaginationBounds({ page: 3, pageSize: 10 }, 5)
    assert.equal(result.maxPage, 1)
    assert.equal(result.correctedPage, 1)
})

test('watch corrects page from 5 to 2 when data shrinks to 15 rows', () => {
    const result = syncPaginationBounds({ page: 5, pageSize: 10 }, 15)
    assert.equal(result.maxPage, 2)
    assert.equal(result.correctedPage, 2)
})

// ---------------------------------------------------------------------------
// Edge cases
// ---------------------------------------------------------------------------

test('watch handles zero rows -- maxPage is 1, page corrected to 1', () => {
    const result = syncPaginationBounds({ page: 3, pageSize: 10 }, 0)
    assert.equal(result.itemCount, 0)
    assert.equal(result.maxPage, 1)
    assert.equal(result.correctedPage, 1)
})

test('watch handles exactly pageSize rows', () => {
    const result = syncPaginationBounds({ page: 1, pageSize: 10 }, 10)
    assert.equal(result.maxPage, 1)
    assert.equal(result.correctedPage, 1)
})

test('watch handles exactly pageSize + 1 rows', () => {
    const result = syncPaginationBounds({ page: 1, pageSize: 10 }, 11)
    assert.equal(result.maxPage, 2)
    assert.equal(result.correctedPage, 1)
})

test('watch uses SYMBOL_PAGE_SIZE fallback when pageSize is undefined', () => {
    const result = syncPaginationBounds({ page: 1 }, 25)
    assert.equal(result.maxPage, 3) // ceil(25/10) = 3
})

// ---------------------------------------------------------------------------
// Source verification
// ---------------------------------------------------------------------------

test('source has watch on perSymbol', () => {
    assert.match(source, /watch\(\s*perSymbol\s*,/)
})

test('source watch delegates page correction to syncPaginationBounds', () => {
    assert.match(source, /syncPaginationBounds\(symbolPagination, rows\.length\)/)
})

test('syncPaginationBounds sets itemCount', () => {
    assert.match(source, /pagination\.itemCount = itemCount/)
})

test('syncPaginationBounds computes maxPage with Math.ceil', () => {
    assert.match(source, /Math\.ceil\(itemCount \/ pageSize\)/)
})

test('syncPaginationBounds corrects page when it exceeds maxPage', () => {
    assert.match(source, /\(pagination\.page \?\? 1\) > maxPage/)
    assert.match(source, /pagination\.page = maxPage/)
})
