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

test('closed trade replay chart waits for layout before painting candles', () => {
    // Regression: VIRTUAL/USDC closed replay mounted a TradingView frame with
    // background-only canvases even though the fallback candle endpoint returned
    // data. The series population must happen after the expanded row has a
    // measured chart container.
    assert.ok(
        closedTradeExpandedRowSource.includes('class="closed-trade-chart-panel"') &&
            closedTradeExpandedRowSource.includes('flex-wrap: nowrap') &&
            closedTradeExpandedRowSource.includes('min-width: 0'),
        'expected closed trade replay chart to own a stable flex slot',
    )
    assert.ok(
        tradeReplayChartSource.includes('await nextTick()') &&
            tradeReplayChartSource.includes('await nextAnimationFrame()') &&
            tradeReplayChartSource.includes('MAX_PRICE_FORMAT_PRECISION = 8') &&
            tradeReplayChartSource.includes('normalizePriceFormatPrecision(props.precision)') &&
            tradeReplayChartSource.includes('candlestickSeries.setData(localTickerData)') &&
            tradeReplayChartSource.includes('loadError.value = error instanceof Error') &&
            tradeReplayChartSource.includes('if (!chartRef.value)') &&
            tradeReplayChartSource.includes(
                'No candle data available for this replay window.',
            ),
        'expected replay chart to defer candle painting and expose explicit fallback states',
    )
})
