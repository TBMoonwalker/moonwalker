const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

const openTradeExpandedRowSource = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'components', 'OpenTradeExpandedRow.vue'),
    'utf8',
)

test('open sidestep replay waits for execution history before mounting the chart', () => {
    // Regression: the open sidestep replay chart mounted immediately with the
    // fallback current-leg markers, then never re-initialized after the full
    // campaign execution ledger loaded. That left sidestep exit markers out of
    // the TradingView chart even though they were present in the timeline.
    assert.ok(
        openTradeExpandedRowSource.includes('v-if="chartReady"') &&
            openTradeExpandedRowSource.includes('const requiresExecutionHistory = computed(') &&
            openTradeExpandedRowSource.includes('const executionHistoryResolved = ref(') &&
            openTradeExpandedRowSource.includes('const chartReady = computed(') &&
            openTradeExpandedRowSource.includes('executionHistoryResolved.value = true'),
        'expected sidestep open-trade replays to wait for execution history before mounting the chart',
    )
})
