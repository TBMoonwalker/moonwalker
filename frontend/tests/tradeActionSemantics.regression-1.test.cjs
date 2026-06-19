const assert = require('node:assert')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

const rootDir = path.resolve(__dirname, '..')
const columnsSource = fs.readFileSync(
    path.join(rootDir, 'src/composables/useOpenTradeColumns.ts'),
    'utf8',
)
const openTradesSource = fs.readFileSync(
    path.join(rootDir, 'src/components/OpenTrades.vue'),
    'utf8',
)
const helpersSource = fs.readFileSync(
    path.join(rootDir, 'src/helpers/openTrades.ts'),
    'utf8',
)

test('open trade row actions prioritize sell and avoid duplicate buy controls', () => {
    assert.ok(
        columnsSource.includes("onClick: () => options.onDealSell(rowData)") &&
            columnsSource.includes("{ default: () => 'Sell' }"),
        'the primary open-trade row action should sell the trade',
    )
    assert.ok(
        !columnsSource.includes("{ default: () => 'Buy' }"),
        'the row action strip should not duplicate the buy action',
    )
    assert.ok(
        !columnsSource.includes('onDealBuy') &&
            !openTradesSource.includes('onDealBuy'),
        'open-trade columns should not expose the old direct buy row action',
    )
})

test('open trade overflow actions keep secondary actions without duplicating stop', () => {
    assert.ok(
        columnsSource.includes("label: 'Add manual buy'") &&
            columnsSource.includes('disabled: isBuyBlocked(rowData)'),
        'manual buy should remain in the overflow menu and respect buy blocking',
    )
    assert.ok(
        columnsSource.includes("{ default: () => 'Stop' }"),
        'the row action strip should keep the visible stop action',
    )
    assert.ok(
        !columnsSource.includes("key: 'stop'") &&
            !columnsSource.includes("key === 'stop'") &&
            !columnsSource.includes("label: 'Stop'"),
        'the overflow menu should not duplicate the visible stop action',
    )
    assert.ok(
        !columnsSource.includes('Stop and close') &&
            !helpersSource.includes('Stop and close'),
        'user-facing stop copy should not imply a missing close action',
    )
})

test('open trade automation controls live in the overflow menu only', () => {
    assert.ok(
        columnsSource.includes("label: rowData.automation_paused") &&
            columnsSource.includes("'Resume automation'") &&
            columnsSource.includes("'Pause automation'"),
        'pause and resume automation should be exposed through the overflow menu',
    )
    assert.ok(
        columnsSource.includes("key === 'resume'") &&
            columnsSource.includes('void options.onResumeMission(rowData)') &&
            columnsSource.includes("key === 'pause'") &&
            columnsSource.includes('void options.onPauseMission(rowData)'),
        'overflow automation actions should call the mission pause/resume handlers',
    )
    assert.ok(
        !columnsSource.includes('renderAutomationButton') &&
            !columnsSource.includes("{ default: () => 'Pause' }") &&
            !columnsSource.includes("{ default: () => 'Resume' }"),
        'pause and resume should not render as visible row buttons',
    )
})
