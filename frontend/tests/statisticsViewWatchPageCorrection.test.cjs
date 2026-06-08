const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

const source = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'views', 'StatisticsView.vue'),
    'utf8',
)

// ---------------------------------------------------------------------------
// Functional mirror of the watch(perSymbol) page correction logic
// ---------------------------------------------------------------------------

const SYMBOL_PAGE_SIZE = 10

function correctPaginationOnDataChange(rows, currentPage, currentPageSize) {
    const pageSize = currentPageSize ?? SYMBOL_PAGE_SIZE
    const itemCount = rows.length
    const maxPage = Math.max(1, Math.ceil(rows.length / pageSize))
    let correctedPage = currentPage ?? 1
    if (correctedPage > maxPage) {
        correctedPage = maxPage
    }
    return { itemCount, maxPage, correctedPage }
}

// ---------------------------------------------------------------------------
// Normal data -- page stays the same
// ---------------------------------------------------------------------------

test('watch keeps page 1 when data has 25 rows', () => {
    const rows = Array.from({ length: 25 }, (_, i) => i)
    const result = correctPaginationOnDataChange(rows, 1, 10)
    assert.equal(result.itemCount, 25)
    assert.equal(result.maxPage, 3)
    assert.equal(result.correctedPage, 1)
})

test('watch keeps page 3 when data has 30 rows', () => {
    const rows = Array.from({ length: 30 }, (_, i) => i)
    const result = correctPaginationOnDataChange(rows, 3, 10)
    assert.equal(result.maxPage, 3)
    assert.equal(result.correctedPage, 3)
})

// ---------------------------------------------------------------------------
// Data shrinks -- page is corrected downward
// ---------------------------------------------------------------------------

test('watch corrects page from 3 to 1 when data shrinks to 5 rows', () => {
    const rows = Array.from({ length: 5 }, (_, i) => i)
    const result = correctPaginationOnDataChange(rows, 3, 10)
    assert.equal(result.maxPage, 1)
    assert.equal(result.correctedPage, 1)
})

test('watch corrects page from 5 to 2 when data shrinks to 15 rows', () => {
    const rows = Array.from({ length: 15 }, (_, i) => i)
    const result = correctPaginationOnDataChange(rows, 5, 10)
    assert.equal(result.maxPage, 2)
    assert.equal(result.correctedPage, 2)
})

// ---------------------------------------------------------------------------
// Edge cases
// ---------------------------------------------------------------------------

test('watch handles zero rows -- maxPage is 1, page corrected to 1', () => {
    const result = correctPaginationOnDataChange([], 3, 10)
    assert.equal(result.itemCount, 0)
    assert.equal(result.maxPage, 1)
    assert.equal(result.correctedPage, 1)
})

test('watch handles exactly pageSize rows', () => {
    const rows = Array.from({ length: 10 }, (_, i) => i)
    const result = correctPaginationOnDataChange(rows, 1, 10)
    assert.equal(result.maxPage, 1)
    assert.equal(result.correctedPage, 1)
})

test('watch handles exactly pageSize + 1 rows', () => {
    const rows = Array.from({ length: 11 }, (_, i) => i)
    const result = correctPaginationOnDataChange(rows, 1, 10)
    assert.equal(result.maxPage, 2)
    assert.equal(result.correctedPage, 1)
})

test('watch uses SYMBOL_PAGE_SIZE fallback when pageSize is undefined', () => {
    const rows = Array.from({ length: 25 }, (_, i) => i)
    const result = correctPaginationOnDataChange(rows, 1, undefined)
    assert.equal(result.maxPage, 3) // ceil(25/10) = 3
})

// ---------------------------------------------------------------------------
// Source verification
// ---------------------------------------------------------------------------

test('source has watch on perSymbol', () => {
    assert.match(source, /watch\(perSymbol/)
})

test('source watch sets itemCount', () => {
    assert.match(source, /symbolPagination\.itemCount = rows\.length/)
})

test('source watch computes maxPage with Math.ceil', () => {
    assert.match(source, /Math\.ceil\(rows\.length \/ pageSize\)/)
})

test('source watch corrects page when it exceeds maxPage', () => {
    assert.match(source, /symbolPagination\.page \?\? 1\) > maxPage/)
    assert.match(source, /symbolPagination\.page = maxPage/)
})
