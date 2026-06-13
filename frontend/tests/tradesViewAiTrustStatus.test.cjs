const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

const tradesViewSource = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'views', 'TradesView.vue'),
    'utf8',
)

test('trades page status strip surfaces AI provider unavailable state', () => {
    assert.match(tradesViewSource, /aiTrustRuntimeStatus/)
    assert.match(tradesViewSource, /provider_unavailable/)
    assert.match(tradesViewSource, /AI unavailable/)
    assert.match(tradesViewSource, /New entries are blocked until AI answers successfully/)
})

test('trades page status strip keeps global pause as highest priority', () => {
    assert.match(
        tradesViewSource,
        /if \(tradingPaused\.value\) return 'Moonwalker paused'/,
    )
    assert.match(
        tradesViewSource,
        /tradingPaused\.value \|\| tradeAdmissionWarning\.value/,
    )
})
