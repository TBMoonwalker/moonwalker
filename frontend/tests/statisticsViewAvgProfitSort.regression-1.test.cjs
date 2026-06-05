const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

const source = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'views', 'StatisticsView.vue'),
    'utf8',
)

// ---------------------------------------------------------------------------
// Regression: avg_profit column has sorter but no sortOrder binding
//
// When a column defines sorter: 'default' the user can click the header
// to sort.  Without a sortOrder binding the column header never shows the
// active sort arrow / indicator, creating a confusing UX.
// ---------------------------------------------------------------------------

test('avg_profit column has a sorter defined', () => {
    // Confirm the column is sortable
    assert.match(source, /title: 'Avg Profit'[\s\S]*?sorter: 'default'/)
})

test('avg_profit column has a sortOrder binding', () => {
    // The avg_profit column block should contain a sortOrder property
    // that mirrors the pattern used by win_rate and total_profit.
    // Extract the avg_profit column block and check for sortOrder.
    const avgProfitBlock = source.match(
        /title: 'Avg Profit'[\s\S]*?title: 'Avg Duration'/,
    )
    assert.ok(avgProfitBlock, 'avg_profit column block should exist')
    assert.match(
        avgProfitBlock[0],
        /sortOrder/,
        'avg_profit column should have a sortOrder binding so the sort indicator displays',
    )
})

// ---------------------------------------------------------------------------
// Verify the pattern: every sortable column must have sortOrder
// ---------------------------------------------------------------------------

test('every column with sorter also has sortOrder', () => {
    // Find all column definitions in getSymbolColumns
    const columnsMatch = source.match(
        /function getSymbolColumns[\s\S]*?return \[([\s\S]*?)\]/,
    )
    assert.ok(columnsMatch, 'getSymbolColumns function should exist')

    const columnsBody = columnsMatch[1]
    // Split into individual column objects (rough heuristic)
    const columnBlocks = columnsBody.split(/title:/)

    let issues = []
    for (const block of columnBlocks) {
        if (!block.trim()) continue
        const titleMatch = block.match(/'([^']+)'/)
        const title = titleMatch ? titleMatch[1] : '(unknown)'

        const hasSorter = /sorter: 'default'/.test(block)
        const hasSortOrder = /sortOrder:/.test(block)

        if (hasSorter && !hasSortOrder) {
            issues.push(title)
        }
    }

    assert.deepEqual(
        issues,
        [],
        `Columns with sorter but missing sortOrder: ${issues.join(', ')}`,
    )
})
