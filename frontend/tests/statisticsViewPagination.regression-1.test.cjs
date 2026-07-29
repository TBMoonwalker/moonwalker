const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

const source = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'views', 'StatisticsView.vue'),
    'utf8',
)

// ---------------------------------------------------------------------------
// 1. Pagination wiring
// ---------------------------------------------------------------------------

test('statistics view wires @update:page to handleSymbolPageChange', () => {
    assert.match(source, /@update:page="handleSymbolPageChange"/)
    assert.match(source, /function handleSymbolPageChange/)
    assert.match(source, /symbolPagination\.page = page/)
})

test('statistics view data table uses remote flag for manual pagination', () => {
    assert.match(source, /remote\s/)
})

test('statistics view passes sortedAndPaginatedSymbols as table data', () => {
    assert.match(source, /:data="sortedAndPaginatedSymbols"/)
})

// ---------------------------------------------------------------------------
// 2. Sorting wiring
// ---------------------------------------------------------------------------

test('statistics view wires @update:sorter to handleSymbolSorterChange', () => {
    assert.match(source, /@update:sorter="handleSymbolSorterChange"/)
})

test('handleSymbolSorterChange normalizes sorter payload', () => {
    assert.match(source, /sorter\.columnKey \?\? sorter\.key/)
    assert.match(source, /sorter\.order/)
})

test('handleSymbolSorterChange resets pagination to page 1', () => {
    assert.match(source, /symbolPagination\.page = 1/)
})

test('handleSymbolSorterChange sets symbolSortState to null when sorter is falsy', () => {
    assert.match(source, /symbolSortState\.value = null/)
})

// ---------------------------------------------------------------------------
// 3. symbolSortState default value
// ---------------------------------------------------------------------------

test('symbolSortState defaults to trades descend', () => {
    assert.match(source, /columnKey: 'trades'/)
    assert.match(source, /order: 'descend'/)
})

// ---------------------------------------------------------------------------
// 4. sortedAndPaginatedSymbols computed — sort + slice logic
// ---------------------------------------------------------------------------

test('sortedAndPaginatedSymbols normalizes string values to lowercase', () => {
    assert.match(source, /typeof aVal === 'string'/)
    assert.match(source, /aVal = aVal\.toLowerCase\(\)/)
    assert.match(source, /typeof bVal === 'string'/)
    assert.match(source, /bVal = bVal\.toLowerCase\(\)/)
})

test('sortedAndPaginatedSymbols sort respects ascend vs descend order', () => {
    assert.match(source, /ss\.order === 'ascend' \? -1 : 1/)
    assert.match(source, /ss\.order === 'ascend' \? 1 : -1/)
})

test('sortedAndPaginatedSymbols computes start index from page and pageSize', () => {
    assert.match(source, /symbolPagination\.page \?\? 1/)
    assert.match(source, /symbolPagination\.pageSize \?\? SYMBOL_PAGE_SIZE/)
})

test('sortedAndPaginatedSymbols slices rows by pageSize', () => {
    assert.match(source, /rows\.slice\(start/)
})

test('sortedAndPaginatedSymbols copies perSymbol array before sorting', () => {
    assert.match(source, /\[\.\.\.perSymbol\.value\]/)
})

// ---------------------------------------------------------------------------
// 5. Column sort order binding
// ---------------------------------------------------------------------------

test('Trades column sortOrder uses columnSortOrder helper', () => {
    assert.match(source, /sortOrder: columnSortOrder\('trades'\)/)
})

test('Win Rate column sortOrder uses columnSortOrder helper', () => {
    assert.match(source, /sortOrder: columnSortOrder\('win_rate'\)/)
})

test('Total Profit column sortOrder uses columnSortOrder helper', () => {
    assert.match(source, /sortOrder: columnSortOrder\('total_profit'\)/)
})

// ---------------------------------------------------------------------------
// 6. watch(perSymbol) — pagination correction
// ---------------------------------------------------------------------------

test('watch on perSymbol corrects page when it exceeds maxPage', () => {
    assert.match(source, /watch\(perSymbol/)
    assert.match(source, /Math\.ceil\(rows\.length \/ pageSize\)/)
    assert.match(source, /symbolPagination\.page \?\? 1\) > maxPage/)
})

// ---------------------------------------------------------------------------
// 7. fmtRangePct handles negative zero
// ---------------------------------------------------------------------------

test('fmtRangePct normalizes negative zero to 0', () => {
    assert.match(source, /Object\.is\(val, -0\)/)
})

// ---------------------------------------------------------------------------
// 8. fmtProfitRange — single value vs range
// ---------------------------------------------------------------------------

test('fmtProfitRange returns single value when min equals max', () => {
    assert.match(source, /row\.min === row\.max/)
    assert.match(source, /fmtRangePct\(row\.min\)/)
})

test('fmtProfitRange returns range string when min differs from max', () => {
    assert.match(source, /fmtRangePct\(row\.min\).*to.*fmtRangePct\(row\.max\)/)
})

// ---------------------------------------------------------------------------
// 9. Import SorterResult type
// ---------------------------------------------------------------------------

test('StatisticsView imports SorterResult from naive-ui', () => {
    assert.match(source, /SorterResult.*from 'naive-ui'/)
})

// ---------------------------------------------------------------------------
// 10. Empty state conditions
// ---------------------------------------------------------------------------

test('StatisticsView shows empty state when perSymbol is empty', () => {
    assert.match(source, /No symbol data available/)
})

test('StatisticsView shows empty state when duration data is missing', () => {
    assert.match(source, /No duration data available/)
})

test('StatisticsView shows loading, error, and no-data states when summary is missing', () => {
    assert.match(source, /analytics\.loading/)
    assert.match(source, /analytics\.error/)
    assert.match(source, /No closed trades yet/)
})

// ---------------------------------------------------------------------------
// 11. Heatmap summary singular/plural
// ---------------------------------------------------------------------------

test('heatmapSummary uses singular "active day" when count is 1', () => {
    assert.match(source, /activeDays === 1 \? 'active day' : 'active days'/)
})

// ---------------------------------------------------------------------------
// 12. Resize handler and lifecycle
// ---------------------------------------------------------------------------

test('statistics uses the shared viewport source', () => {
    assert.match(source, /import \{ useViewport \} from '\.\.\/composables\/useViewport'/)
    assert.match(source, /const \{ isMobile \} = useViewport\(\)/)
})

test('shared viewport changes reduce pagination slots on mobile', () => {
    assert.match(source, /const pageSlot = isMobile\.value \? 3 : 5/)
    assert.match(source, /symbolPagination\.pageSlot = pageSlot/)
    assert.match(source, /recentPredictionsPagination\.pageSlot = pageSlot/)
    assert.match(source, /badEntryReviewPagination\.pageSlot = pageSlot/)
    assert.match(
        source,
        /watch\(isMobile, syncPaginationSlots, \{ immediate: true \}\)/,
    )
})

test('onActivated refreshes analytics for kept-alive route visits', () => {
    assert.match(source, /onActivated\(\(\) => \{/)
    assert.match(source, /void analytics\.load\(\)/)
})

test('statistics does not own a window resize listener', () => {
    assert.doesNotMatch(source, /addEventListener\('resize'/)
    assert.doesNotMatch(source, /removeEventListener\('resize'/)
})

// ---------------------------------------------------------------------------
// 13. Mobile table shape
// ---------------------------------------------------------------------------

test('statistics view defines compact mobile column sets', () => {
    assert.match(source, /const SYMBOL_MOBILE_COLUMN_KEYS = new Set/)
    assert.match(source, /const DURATION_MOBILE_COLUMN_KEYS = new Set/)
    assert.match(source, /const AI_TRUST_MOBILE_COLUMN_KEYS = new Set/)
})

test('statistics view removes fixed first columns on mobile', () => {
    assert.match(source, /fixed: isMobile\.value \? undefined : 'left'/)
})

test('statistics view uses shorter mobile scroll widths', () => {
    assert.match(source, /:scroll-x="isMobile \? 346 : 500"/)
    assert.match(source, /:scroll-x="isMobile \? 382 : 1000"/)
})

test('statistics tabs wrap into a two-column mobile grid', () => {
    assert.match(source, /\.statistics-tabs :deep\(\.n-tabs-nav-scroll-content\)/)
    assert.match(source, /grid-template-columns: repeat\(2, minmax\(0, 1fr\)\)/)
})

test('statistics pagination hides the wrapping count prefix on mobile', () => {
    assert.match(source, /\.ledger-panel :deep\(\.n-pagination-prefix\)/)
    assert.match(source, /display: none;/)
})
