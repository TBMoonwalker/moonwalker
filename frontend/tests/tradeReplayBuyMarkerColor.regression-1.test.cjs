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
        tradeReplayChartSource.includes("upColor: '#2E7D5B'"),
          'expected the replay chart bullish candle color to use DESIGN.md success green',
      )
    assert.ok(
        openTradeExpandedRowSource.includes(
              "const BUY_MARKER_COLOR = '#2E7D5B'",
          ),
          'expected open-trade buy markers to use DESIGN.md success green',
      )
     assert.ok(
         closedTradeExpandedRowSource.includes(
                "const BUY_MARKER_COLOR = '#2E7D5B'",
            ),
            'expected closed-trade buy markers to use DESIGN.md success green',
        )
     assert.ok(
         tradeReplayChartSource.includes('Date.parse(String(value))'),
          'expected replay charts to parse timestamp strings when anchoring execution history',
      )
 })
