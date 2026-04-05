const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

const closedTradesSource = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'components', 'ClosedTrades.vue'),
    'utf8',
)
const closedTradeExpandedRowSource = fs.readFileSync(
    path.join(
        __dirname,
        '..',
        'src',
        'components',
        'ClosedTradeExpandedRow.vue',
    ),
    'utf8',
)
const tradeReplayChartSource = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'components', 'TradeReplayChart.vue'),
    'utf8',
)

test('legacy closed trades remain expandable with replay fallback copy', () => {
    // Regression: ISSUE-001 — legacy closed rows without deal_id had no expander,
    // so users had no in-table explanation that replay history is unavailable.
    // Found by /qa on 2026-04-04
    // Report: .gstack/qa-reports/qa-report-127-0-0-1-2026-04-04.md
    assert.ok(
        closedTradesSource.includes('expandable: () => true,'),
        'expected all closed trade rows to stay expandable',
    )
    assert.ok(
        closedTradeExpandedRowSource.includes(
            'Legacy closed trade without execution history.',
        ),
        'expected legacy replay fallback copy in expanded closed trade rows',
    )
    assert.ok(
        tradeReplayChartSource.includes('return Array.isArray(payload) ? payload : []'),
        'expected replay chart to normalize empty OHLCV payloads before mapping',
    )
})
