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

test('closed trade replay backs exact sell markers with overlay series data', () => {
    // Regression: the closed-trade replay archive can end before the final sell
    // execution timestamp. Marker-only exact-price placement still snaps to the
    // last candle and can disappear off-scale, so the chart needs a dedicated
    // overlay series carrying the exact sell time and price.
    // Found by /investigate on 2026-04-09 using the local PHA/USDC replay.
    assert.ok(
        closedTradeExpandedRowSource.includes('const hasExactFinalSellPrice =') &&
            closedTradeExpandedRowSource.includes("'atPriceMiddle' as const") &&
            closedTradeExpandedRowSource.includes('{ price: finalSellPrice }') &&
            closedTradeExpandedRowSource.includes("title: 'SELL'"),
        'expected closed trades to pass the final sell price into chart markers and price lines',
    )
    assert.ok(
        tradeReplayChartSource.includes('LineSeries,') &&
            tradeReplayChartSource.includes('function normalizeExactMarkerTime(') &&
            tradeReplayChartSource.includes('const exactMarkerData = props.markers') &&
            tradeReplayChartSource.includes('const exactMarkerSeries = chart.addSeries(LineSeries, {') &&
            tradeReplayChartSource.includes('exactMarkerSeries.setData(') &&
            tradeReplayChartSource.includes(
                'createSeriesMarkers(exactMarkerSeries, exactMarkerData)',
            ),
        'expected the replay chart to back exact-price markers with a dedicated overlay series',
    )
})
