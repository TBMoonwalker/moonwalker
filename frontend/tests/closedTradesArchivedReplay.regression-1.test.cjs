const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

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

test('closed trades prefer archived replay candles before shared ticker fallback', () => {
    // Regression: closed-trade replay used shared tickers only, so housekeeping
    // and full backup/restore could erase candle history for old closed rows.
    // Found by /investigate on 2026-04-05
    assert.ok(
        closedTradeExpandedRowSource.includes(
            ':archive-deal-id="props.rowData.deal_id"',
        ),
        'expected closed trades to pass the replay deal id into the chart',
    )
    assert.ok(
        tradeReplayChartSource.includes('/data/ohlcv/replay/') &&
            tradeReplayChartSource.includes('${historyStart}/${historyEnd}/0'),
        'expected the chart to request archived replay candles first',
    )
})
