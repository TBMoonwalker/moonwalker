const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

const rootDir = path.resolve(__dirname, '..')
const tradesViewSource = fs.readFileSync(
    path.join(rootDir, 'src/views/TradesView.vue'),
    'utf8',
)
const openTradeExpandedRowSource = fs.readFileSync(
    path.join(rootDir, 'src/components/OpenTradeExpandedRow.vue'),
    'utf8',
)
const waitingCampaignsSource = fs.readFileSync(
    path.join(rootDir, 'src/components/WaitingCampaigns.vue'),
    'utf8',
)
const closedTradesSource = fs.readFileSync(
    path.join(rootDir, 'src/components/ClosedTrades.vue'),
    'utf8',
)
const unsellableTradesSource = fs.readFileSync(
    path.join(rootDir, 'src/components/UnsellableTrades.vue'),
    'utf8',
)

test('expanded open trade manual-order action keeps readable dark-mode text', () => {
    assert.ok(
        openTradeExpandedRowSource.includes('class="manual-order-button"') &&
            openTradeExpandedRowSource.includes('--n-text-color: var(--mw-color-text-primary)') &&
            openTradeExpandedRowSource.includes('--n-color: var(--mw-color-primary-soft)'),
        'expected the manual order button to use theme-backed text and surface colors',
    )
})

test('unsellable tab relies on the count chip without an extra warning icon', () => {
    assert.ok(
        !tradesViewSource.includes('AlertCircleOutline') &&
            !tradesViewSource.includes('<n-icon v-if="unsellableTradesCount > 0"'),
        'expected the unsellable tab to avoid a duplicate warning icon',
    )
    assert.ok(
        tradesViewSource.includes('class="trade-tab-count"'),
        'expected the unsellable count chip to remain as the status indicator',
    )
})

test('secondary trade tables reuse the open-trades ledger cell language', () => {
    for (const [name, source] of [
        ['waiting campaigns', waitingCampaignsSource],
        ['closed trades', closedTradesSource],
        ['unsellable trades', unsellableTradesSource],
    ]) {
        assert.ok(
            source.includes('trade-symbol-cell') &&
                source.includes('trade-symbol-main') &&
                source.includes('trade-cell-stack') &&
                source.includes('trade-cell-sub') &&
                source.includes('trade-row-actions'),
            `expected ${name} to use the shared ledger table classes`,
        )
    }
})

test('waiting campaigns match the open-trades ledger row rhythm', () => {
    assert.ok(
        !waitingCampaignsSource.includes(':single-line="false"'),
        'expected waiting campaigns to use the same compact table row behavior as open trades',
    )
    assert.ok(
        !waitingCampaignsSource.includes('NSlider'),
        'expected waiting campaigns to use the shared TP/SO beam instead of a slider control',
    )
    assert.ok(
        waitingCampaignsSource.includes(
            "class: ['trade-tpso-cell', 'waiting-reentry-cell', toneClass]",
        ),
        'expected waiting re-entry state to reuse the shared ledger beam classes',
    )
    assert.ok(
        waitingCampaignsSource.includes(
            "h('span', { class: getStatusToneClass(rowData) }, status)",
        ),
        'expected waiting status to render as ledger text instead of a separate pill style',
    )
    assert.ok(
        waitingCampaignsSource.includes("{ default: () => 'Activate' }") &&
            !waitingCampaignsSource.includes("{ default: () => 'Switch to active' }"),
        'expected the visible waiting primary action to stay short enough for the shared action row',
    )
})
