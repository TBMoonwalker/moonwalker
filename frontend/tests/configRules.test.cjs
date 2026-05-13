const assert = require('node:assert/strict')
const test = require('node:test')

const { loadFrontendModule } = require('./helpers/loadFrontendModule.cjs')

const { buildConfigRules } = loadFrontendModule('src/helpers/configRules.ts')

function createRuleContext(overrides = {}) {
    const state = {
        dca: {
            value: {
                enabled: true,
                trade_mode: 'dynamic_dca',
            },
        },
        exchange: {
            value: {
                market: 'spot',
            },
        },
        signal: {
            value: {
                asap_symbol_select: [],
                asap_use_url: false,
                csvsignal_inline: null,
                csvsignal_mode: null,
                csvsignal_source: null,
                signal: 'asap',
                symbol_list: null,
            },
        },
        submitAttempted: {
            value: true,
        },
        getAsapMissingFieldsLabel: () => 'exchange key and timeframe',
        isAsapExchangeReady: () => true,
        isCurrencyConfigured: () => true,
        isUrlInput: (value) => /^https?:\/\//i.test(String(value || '')),
        ...overrides,
    }

    return {
        state,
        rules: buildConfigRules(state),
    }
}

test('config rules validate ASAP URL mode and exchange prerequisites', () => {
    const invalidUrl = createRuleContext({
        signal: {
            value: {
                asap_symbol_select: [],
                asap_use_url: true,
                csvsignal_inline: null,
                csvsignal_mode: null,
                csvsignal_source: null,
                signal: 'asap',
                symbol_list: 'ftp://signals.example/list.txt',
            },
        },
    })
    assert.equal(
        invalidUrl.rules.symbol_list.validator().message,
        'Please provide a valid URL (http/https)',
    )

    const missingCurrency = createRuleContext({
        isCurrencyConfigured: () => false,
    })
    assert.equal(
        missingCurrency.rules.symbol_list.validator().message,
        'Please configure currency before selecting symbols',
    )

    const missingExchange = createRuleContext({
        isAsapExchangeReady: () => false,
    })
    assert.equal(
        missingExchange.rules.symbol_list.validator().message,
        'Please configure exchange key and timeframe before selecting symbols',
    )

    const missingSymbols = createRuleContext()
    assert.equal(
        missingSymbols.rules.symbol_list.validator().message,
        'Please select at least one symbol',
    )
})

test('config rules gate CSV validation by mode and submit state', () => {
    const sourceContext = createRuleContext({
        signal: {
            value: {
                asap_symbol_select: [],
                asap_use_url: false,
                csvsignal_inline: null,
                csvsignal_mode: 'source',
                csvsignal_source: '',
                signal: 'csv_signal',
                symbol_list: null,
            },
        },
    })
    assert.equal(
        sourceContext.rules.csv_signal_source.validator().message,
        'Please add CSV source path or URL',
    )
    assert.equal(sourceContext.rules.csv_signal_inline.validator(), true)

    const inlineContext = createRuleContext({
        signal: {
            value: {
                asap_symbol_select: [],
                asap_use_url: false,
                csvsignal_inline: '',
                csvsignal_mode: 'inline',
                csvsignal_source: null,
                signal: 'csv_signal',
                symbol_list: null,
            },
        },
    })
    assert.equal(
        inlineContext.rules.csv_signal_inline.validator().message,
        'Please paste CSV text or upload a CSV file',
    )

    const untouchedContext = createRuleContext({
        submitAttempted: { value: false },
    })
    assert.equal(untouchedContext.rules.signal.validator({}, null), true)
})

test('config rules require only dynamic DCA fields in dynamic mode', () => {
    const disabledContext = createRuleContext({
        dca: {
            value: {
                enabled: false,
                trade_mode: 'dynamic_dca',
            },
        },
    })
    assert.equal(disabledContext.rules.mstc.validator({}, null), true)
    assert.equal(disabledContext.rules.sos.validator({}, null), true)

    const dynamicContext = createRuleContext({
        dca: {
            value: {
                enabled: true,
                trade_mode: 'dynamic_dca',
            },
        },
    })
    assert.equal(
        dynamicContext.rules.mstc.validator({}, null).message,
        'Please add max safety order count',
    )
    assert.equal(
        dynamicContext.rules.sos.validator({}, null).message,
        'Please add price deviation',
    )

    const sidestepContext = createRuleContext({
        dca: {
            value: {
                enabled: true,
                trade_mode: 'sidestep',
            },
        },
    })
    assert.equal(sidestepContext.rules.so.validator({}, null), true)
    assert.equal(sidestepContext.rules.mstc.validator({}, null), true)
    assert.equal(sidestepContext.rules.sos.validator({}, null), true)
    assert.equal(sidestepContext.rules.ss.validator({}, null), true)
    assert.equal(sidestepContext.rules.os.validator({}, null), true)
})

test('config rules require sidestep strategies only for spot sidestep mode', () => {
    const sidestepContext = createRuleContext({
        dca: {
            value: {
                enabled: true,
                trade_mode: 'sidestep',
            },
        },
        exchange: {
            value: {
                market: 'spot',
            },
        },
    })

    assert.equal(
        sidestepContext.rules.sidestep_bearish_strategy.validator({}, null).message,
        'Please select bearish sidestep strategy',
    )
    assert.equal(
        sidestepContext.rules.sidestep_reentry_strategy.validator({}, null).message,
        'Please select sidestep re-entry strategy',
    )

    const futuresContext = createRuleContext({
        dca: {
            value: {
                enabled: true,
                trade_mode: 'sidestep',
            },
        },
        exchange: {
            value: {
                market: 'future',
            },
        },
    })

    assert.equal(
        futuresContext.rules.sidestep_bearish_strategy.validator({}, null),
        true,
    )
    assert.equal(
        futuresContext.rules.sidestep_reentry_strategy.validator({}, null),
        true,
    )
})

test('config rules do not require retired ladder fields in canonical dynamic mode', () => {
    const dynamicContext = createRuleContext({
        dca: {
            value: {
                enabled: true,
                trade_mode: 'dynamic_dca',
            },
        },
    })

    assert.equal(dynamicContext.rules.so.validator({}, null), true)
    assert.equal(dynamicContext.rules.ss.validator({}, null), true)
    assert.equal(dynamicContext.rules.os.validator({}, null), true)
})

test('config rules require a positive global max fund after submit', () => {
    const missingContext = createRuleContext()
    assert.equal(
        missingContext.rules.max_fund.validator({}, null).message,
        'Please add global max fund',
    )
    assert.equal(
        missingContext.rules.max_fund.validator({}, 0).message,
        'Please add global max fund',
    )
    assert.equal(missingContext.rules.max_fund.validator({}, 250), true)

    const untouchedContext = createRuleContext({
        submitAttempted: { value: false },
    })
    assert.equal(untouchedContext.rules.max_fund.validator({}, null), true)
})
