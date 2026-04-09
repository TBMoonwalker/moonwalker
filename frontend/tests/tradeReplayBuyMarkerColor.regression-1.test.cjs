const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

const openTradeExpandedRowSource = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'components', 'OpenTradeExpandedRow.vue'),
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

test('trade replay buy markers use the chart bullish green', () => {
    // Regression: the closed-trades replay rollout changed open and closed
    // trade buy markers from the chart bullish green to the darker operator
    // primary, which made the buy arrows visibly dimmer.
    assert.ok(
        tradeReplayChartSource.includes("upColor: 'rgb(99, 226, 183)'"),
        'expected the replay chart bullish candle color to stay bright green',
    )
    assert.ok(
        openTradeExpandedRowSource.includes(
            "const BUY_MARKER_COLOR = 'rgb(99, 226, 183)'",
        ),
        'expected open-trade buy markers to use the bullish chart green',
    )
    assert.ok(
        closedTradeExpandedRowSource.includes(
            "const BUY_MARKER_COLOR = 'rgb(99, 226, 183)'",
        ),
        'expected closed-trade buy markers to use the bullish chart green',
    )
})
