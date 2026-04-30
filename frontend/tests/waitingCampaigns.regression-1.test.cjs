const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

const tradesViewSource = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'views', 'TradesView.vue'),
    'utf8',
)
const waitingCampaignsSource = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'components', 'WaitingCampaigns.vue'),
    'utf8',
)
const closedTradesSource = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'components', 'ClosedTrades.vue'),
    'utf8',
)
const configDcaSectionSource = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'components', 'config', 'ConfigDcaSection.vue'),
    'utf8',
)
const websocketStatusBarSource = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'components', 'WebSocketStatusBar.vue'),
    'utf8',
)
const monitoringSummarySource = fs.readFileSync(
    path.join(
        __dirname,
        '..',
        'src',
        'composables',
        'useControlCenterMonitoringSummary.ts',
    ),
    'utf8',
)

test('waiting sidestep campaigns get their own surface and explicit stop action', () => {
    assert.ok(
        tradesViewSource.includes("name=\"waiting-campaigns\""),
        'expected the trades view to expose a dedicated waiting-campaign tab',
    )
    assert.ok(
        waitingCampaignsSource.includes("websocketId: 'waitingCampaigns'"),
        'expected the waiting campaigns table to read from its dedicated websocket feed',
    )
    assert.ok(
        waitingCampaignsSource.includes('/trades/waiting/stop/${rowData.campaign_id}'),
        'expected the waiting campaigns table to expose a manual stop action',
    )
    assert.ok(
        closedTradesSource.includes("title: 'Outcome'"),
        'expected closed trades to label tactical sidestep exits separately from terminal outcomes',
    )
    assert.ok(
        configDcaSectionSource.includes('sidestep_campaign_enabled'),
        'expected the DCA config section to expose the sidestep campaign toggle',
    )
    assert.ok(
        configDcaSectionSource.includes('sidestep_bearish_strategy'),
        'expected the DCA config section to expose the bearish sidestep strategy selector',
    )
    assert.ok(
        websocketStatusBarSource.includes("useWebSocketDataStore('waitingCampaigns')"),
        'expected the websocket status bar to include waiting campaign stream health',
    )
    assert.ok(
        monitoringSummarySource.includes("label: 'Waiting campaigns'"),
        'expected control-center monitoring summaries to count the waiting campaign stream',
    )
})
