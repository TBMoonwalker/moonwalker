const assert = require('node:assert/strict')
const test = require('node:test')

const { loadFrontendModule } = require('./helpers/loadFrontendModule.cjs')

const { deriveControlCenterReadiness } = loadFrontendModule(
    'src/control-center/readiness.ts',
)
const { deriveControlCenterViewState } = loadFrontendModule(
    'src/control-center/viewState.ts',
)

function createReadyConfig() {
    return {
        timezone: 'Europe/Vienna',
        signal: 'asap',
        exchange: 'binance',
        timeframe: '1h',
        key: 'api-key',
        secret: 'api-secret',
        currency: 'USDT',
        max_bots: 2,
        bo: 20,
        capital_max_fund: 250,
        tp: 1.5,
        history_lookback_time: '180d',
        symbol_list: 'BTC/USDT',
        dry_run: true,
    }
}

test('deriveControlCenterReadiness flags a first-run configuration', () => {
    const readiness = deriveControlCenterReadiness({})

    assert.equal(readiness.complete, false)
    assert.equal(readiness.firstRun, true)
    assert.equal(readiness.attentionNeeded, false)
    assert.equal(readiness.nextMode, 'setup')
    assert.equal(readiness.nextTarget, 'general')
})

test('deriveControlCenterReadiness distinguishes partial setup from healthy setup', () => {
    const partialReadiness = deriveControlCenterReadiness({
        timezone: 'Europe/Vienna',
        signal: 'asap',
        exchange: 'binance',
        timeframe: '1h',
        currency: 'USDT',
    })

    assert.equal(partialReadiness.firstRun, false)
    assert.equal(partialReadiness.attentionNeeded, true)
    assert.equal(partialReadiness.nextTarget, 'exchange')

    const readyReadiness = deriveControlCenterReadiness(createReadyConfig())
    assert.equal(readyReadiness.complete, true)
    assert.equal(readyReadiness.nextTarget, 'live-activation')
    assert.equal(readyReadiness.nextMode, 'overview')
})

test('deriveControlCenterViewState adapts to rescue and post-action success states', () => {
    const readiness = deriveControlCenterReadiness(createReadyConfig())

    const rescueState = deriveControlCenterViewState({
        loadError: 'Request failed',
        readiness,
        transition: null,
    })
    assert.equal(rescueState.kind, 'rescue')
    assert.equal(rescueState.defaultMode, 'overview')

    const successState = deriveControlCenterViewState({
        loadError: null,
        readiness,
        transition: {
            kind: 'save',
            status: 'success',
            message: 'Configuration saved.',
            at: Date.now(),
            mode: 'overview',
        },
    })
    assert.equal(successState.kind, 'post_action_success')
    assert.equal(successState.badge, 'Updated')
})
