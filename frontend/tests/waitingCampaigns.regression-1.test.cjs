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
const openTradeColumnsSource = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'composables', 'useOpenTradeColumns.ts'),
    'utf8',
)
const closedTradesSource = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'components', 'ClosedTrades.vue'),
    'utf8',
)
const missionPauseActionsSource = fs.readFileSync(
    path.join(
        __dirname,
        '..',
        'src',
        'composables',
        'useMissionPauseActions.ts',
    ),
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

test('waiting sidestep campaigns get their own surface and explicit waiting actions', () => {
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
        waitingCampaignsSource.includes('/trades/waiting/activate/${rowData.campaign_id}'),
        'expected the waiting campaigns table to expose a manual switch-to-active action',
    )
    assert.ok(
        waitingCampaignsSource.includes('Switch to active'),
        'expected the waiting campaigns table to label the manual re-entry action clearly',
    )
    assert.ok(
        waitingCampaignsSource.includes('Pause automation'),
        'expected the waiting campaigns table to expose a pause automation control',
    )
    assert.ok(
        openTradeColumnsSource.includes('Pause automation'),
        'expected the open trades table to expose a pause automation control',
    )
    assert.ok(
        openTradeColumnsSource.includes('Automation paused'),
        'expected paused open trades to render a persistent paused-state tag',
    )
    assert.ok(
        missionPauseActionsSource.includes('/trades/mission/${action}/'),
        'expected mission pause actions to use the dedicated mission pause/resume endpoint',
    )
    assert.ok(
        waitingCampaignsSource.includes('sidestep_count'),
        'expected the waiting campaigns table to surface sidestep cycle metadata for active-flat trades',
    )
    assert.ok(
        waitingCampaignsSource.includes('cooldown_until'),
        'expected the waiting campaigns table to surface cooldown timing for waiting campaigns',
    )
    assert.ok(
        waitingCampaignsSource.includes('last_exit_reason'),
        'expected the waiting campaigns table to surface the last exit reason for waiting campaigns',
    )
    assert.ok(
        waitingCampaignsSource.includes('reentry_status'),
        'expected the waiting campaigns table to surface human-readable re-entry status text',
    )
    assert.ok(
        waitingCampaignsSource.includes('display_profit_percent'),
        'expected waiting sidestep campaigns to render mission-level PnL instead of only the flat-phase delta',
    )
    assert.ok(
        openTradeColumnsSource.includes('Re-entered x'),
        'expected active sidestep trades to show a visible re-entry badge in the open-trades table',
    )
    assert.ok(
        openTradeColumnsSource.includes('display_profit_percent'),
        'expected open sidestep trades to render mission-level PnL instead of only the current leg',
    )
    assert.ok(
        tradesViewSource.includes('Moonwalker paused'),
        'expected the trades workspace to surface passive global-pause status copy',
    )
    assert.ok(
        closedTradesSource.includes("title: 'Outcome'"),
        'expected closed trades to label tactical sidestep exits separately from terminal outcomes',
    )
    assert.ok(
        closedTradesSource.includes('sort_key'),
        'expected closed trades pagination requests to include backend sort parameters',
    )
    assert.ok(
        configDcaSectionSource.includes('label="Trade mode"'),
        'expected the DCA config section to expose the canonical trade mode chooser',
    )
    assert.ok(
        configDcaSectionSource.includes('TRADE_MODE_SIDESTEP'),
        'expected the DCA config section to expose sidestep as an operator-facing trade mode',
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
