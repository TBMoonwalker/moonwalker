const assert = require('node:assert/strict')
const test = require('node:test')

const { loadFrontendModule } = require('./helpers/loadFrontendModule.cjs')

const { buildConfigRules } = loadFrontendModule('src/helpers/configRules.ts')

function createRuleContext(overrides = {}) {
    const state = {
        dca: {
            value: {
                dynamic: false,
                enabled: true,
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

test('config rules only require manual DCA fields when needed', () => {
    const disabledContext = createRuleContext({
        dca: {
            value: {
                dynamic: false,
                enabled: false,
            },
        },
    })
    assert.equal(disabledContext.rules.so.validator({}, null), true)

    const dynamicContext = createRuleContext({
        dca: {
            value: {
                dynamic: true,
                enabled: true,
            },
        },
    })
    assert.equal(dynamicContext.rules.so.validator({}, null), true)

    const requiredContext = createRuleContext()
    assert.equal(
        requiredContext.rules.so.validator({}, null).message,
        'Please add safety order amount',
    )
})
