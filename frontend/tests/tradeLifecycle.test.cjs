const assert = require('node:assert/strict')
const test = require('node:test')

const { loadFrontendModule } = require('./helpers/loadFrontendModule.cjs')

const {
    normalizeTradeMode,
    TRADE_MODE_DYNAMIC_DCA,
    TRADE_MODE_SIDESTEP,
} = loadFrontendModule('src/helpers/tradeLifecycle.ts')

test('normalizeTradeMode prefers the canonical trade_mode over legacy mirrors', () => {
    assert.equal(
        normalizeTradeMode(
            TRADE_MODE_DYNAMIC_DCA,
            'sidestep_reentry',
            false,
            true,
        ),
        TRADE_MODE_DYNAMIC_DCA,
    )

    assert.equal(
        normalizeTradeMode(TRADE_MODE_SIDESTEP, 'classic_dca', true, false),
        TRADE_MODE_SIDESTEP,
    )
})

test('normalizeTradeMode falls back to sidestep when legacy sidestep evidence exists', () => {
    assert.equal(
        normalizeTradeMode(null, 'sidestep_reentry', false, false),
        TRADE_MODE_SIDESTEP,
    )

    assert.equal(
        normalizeTradeMode(null, null, false, true),
        TRADE_MODE_SIDESTEP,
    )
})

test('normalizeTradeMode defaults to dynamic_dca when no sidestep evidence exists', () => {
    assert.equal(
        normalizeTradeMode(null, null, false, false),
        TRADE_MODE_DYNAMIC_DCA,
    )

    assert.equal(
        normalizeTradeMode(null, null, true, false),
        TRADE_MODE_DYNAMIC_DCA,
    )
})
