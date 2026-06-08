const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

const tradeReplayChartSource = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'components', 'TradeReplayChart.vue'),
    'utf8',
)
const backtestChartSource = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'components', 'BacktestResultChart.vue'),
    'utf8',
)
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
const indicatorHelperSource = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'helpers', 'tradingViewIndicators.ts'),
    'utf8',
)

test('trade replay charts fetch and render strategy indicator overlays', () => {
    assert.ok(
        tradeReplayChartSource.includes('/trades/replay/indicators/${dealId}/') &&
            tradeReplayChartSource.includes('${timeframe.timerange}/${historyStart}/${indicatorEnd}'),
        'expected replay chart to request strategy indicators for its selected chart window',
    )
    assert.ok(
        tradeReplayChartSource.includes('renderIndicatorSeries(activeChart, series, localOffsetSeconds,') &&
            tradeReplayChartSource.includes('priceMarkersVisible: true') &&
            tradeReplayChartSource.includes('indicatorPanes') &&
            tradeReplayChartSource.includes('class="indicator-chart"'),
        'expected replay chart to render indicator overlays and show price markers',
    )
    assert.ok(
        openTradeExpandedRowSource.includes(':deal-id="props.rowData.deal_id"') &&
            closedTradeExpandedRowSource.includes(':deal-id="props.rowData.deal_id"'),
        'expected open and closed trade replays to pass execution ledger deal ids',
    )
    assert.ok(
        indicatorHelperSource.includes('HistogramSeries') &&
            indicatorHelperSource.includes('priceMarkersVisible') &&
            indicatorHelperSource.includes('withDistinctIndicatorColors') &&
            tradeReplayChartSource.includes('withDistinctIndicatorColors(replayIndicators.value)') &&
            indicatorHelperSource.includes('getIndicatorPanes') &&
            backtestChartSource.includes('../helpers/tradingViewIndicators'),
        'expected replay and backtest charts to share indicator rendering and display color helpers',
    )
})
