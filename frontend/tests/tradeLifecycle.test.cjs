const assert = require('node:assert/strict')
const test = require('node:test')

const { loadFrontendModule } = require('./helpers/loadFrontendModule.cjs')

const {
    normalizeTradeMode,
    TRADE_MODE_DYNAMIC_DCA,
    TRADE_MODE_SIDESTEP,
} = loadFrontendModule('src/helpers/tradeLifecycle.ts')

test('normalizeTradeMode preserves supported canonical trade_mode values', () => {
    assert.equal(normalizeTradeMode(TRADE_MODE_DYNAMIC_DCA), TRADE_MODE_DYNAMIC_DCA)
    assert.equal(normalizeTradeMode(TRADE_MODE_SIDESTEP), TRADE_MODE_SIDESTEP)
})

test('normalizeTradeMode defaults to dynamic_dca when the canonical value is missing or invalid', () => {
    assert.equal(normalizeTradeMode(null), TRADE_MODE_DYNAMIC_DCA)
    assert.equal(normalizeTradeMode('classic_dca'), TRADE_MODE_DYNAMIC_DCA)
})
