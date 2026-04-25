const assert = require('node:assert/strict')
const test = require('node:test')

const { loadFrontendModule } = require('./helpers/loadFrontendModule.cjs')

const { buildLoadedConfigState } = loadFrontendModule(
    'src/helpers/configLoad.ts',
)

function createLoadDefaults(overrides = {}) {
    return {
        clientTimezone: 'Europe/Vienna',
        showAdvancedGeneral: true,
        advancedWsHealthcheckIntervalMs: 30000,
        advancedWsStaleTimeoutMs: 45000,
        advancedWsReconnectDebounceMs: 5000,
        defaultSymSignalUrl: 'https://signals.example/api',
        defaultSymSignalVersion: 'v2',
        defaultTpSpikeConfirmSeconds: 20,
        defaultTpSpikeConfirmTicks: 5,
        defaultGreenPhaseRampDays: 7,
        defaultGreenPhaseEvalIntervalSec: 600,
        defaultGreenPhaseWindowMinutes: 90,
        defaultGreenPhaseMinProfitableCloseRatio: 0.35,
        defaultGreenPhaseSpeedMultiplier: 1.5,
        defaultGreenPhaseExitMultiplier: 1.1,
        defaultGreenPhaseMaxExtraDeals: 4,
        defaultGreenPhaseConfirmCycles: 3,
        defaultGreenPhaseReleaseCycles: 2,
        defaultGreenPhaseMaxLockedFundPercent: 55,
        defaultAutopilotProfitStretchRatio: 0,
        defaultAutopilotProfitStretchMax: 0,
        defaultAutopilotEntryStretchMaxMultiplier: 1,
        defaultAutopilotSafetyStretchMaxMultiplier: 1,
        ...overrides,
    }
}

test(
    'buildLoadedConfigState applies advanced-general defaults and CSV inline parsing',
    () => {
        const defaults = createLoadDefaults({ showAdvancedGeneral: false })

        const state = buildLoadedConfigState(
            {
                timezone: '',
                debug: 'true',
                ws_watchdog_enabled: 'false',
                ws_healthcheck_interval_ms: '9000',
                ws_stale_timeout_ms: '8000',
                ws_reconnect_debounce_ms: '7000',
                exchange_hostname: 'api.exchange.test',
                capital_max_fund: '250',
                capital_reserve_safety_orders: 'false',
                capital_budget_buffer_pct: '0.02',
                autopilot_profit_stretch_enabled: 'true',
                autopilot_profit_stretch_ratio: '0.5',
                autopilot_profit_stretch_max: '75',
                autopilot_entry_stretch_max_multiplier: '2',
                autopilot_safety_stretch_max_multiplier: '1.5',
                signal: 'csv_signal',
                signal_settings: {
                    csv_source: 'pair;side\nBTC/USDT;buy',
                },
                timeframe: '1h',
                history_lookback_time: '',
            },
            defaults,
        )

        assert.equal(state.general.timezone, defaults.clientTimezone)
        assert.equal(state.general.debug, true)
        assert.equal(state.general.ws_watchdog_enabled, false)
        assert.equal(state.general.ws_healthcheck_interval_ms, 9000)
        assert.equal(state.general.ws_stale_timeout_ms, 8000)
        assert.equal(state.general.ws_reconnect_debounce_ms, 7000)
        assert.equal(state.exchange.exchange_hostname, 'api.exchange.test')
        assert.equal(state.signal.csvsignal_mode, 'inline')
        assert.equal(
            state.signal.csvsignal_inline,
            'pair;side\nBTC/USDT;buy',
        )
        assert.equal(state.signal.csvsignal_source, null)
        assert.equal(state.indicator.history_lookback_time, '180d')
        assert.equal(
            state.autopilot.green_phase_ramp_days,
            defaults.defaultGreenPhaseRampDays,
        )
        assert.equal(state.autopilot.symbol_entry_sizing_enabled, false)
        assert.equal(state.capital.max_fund, 250)
        assert.equal(state.capital.reserve_safety_orders, false)
        assert.equal(state.capital.budget_buffer_pct, 0.02)
        assert.equal(state.autopilot.profit_stretch_enabled, true)
        assert.equal(state.autopilot.profit_stretch_ratio, 0.5)
        assert.equal(state.autopilot.profit_stretch_max, 75)
        assert.equal(state.autopilot.entry_stretch_max_multiplier, 2)
        assert.equal(state.autopilot.safety_stretch_max_multiplier, 1.5)
    },
)

test('buildLoadedConfigState distinguishes ASAP URLs from manual symbols', () => {
    const defaults = createLoadDefaults()
    const urlState = buildLoadedConfigState(
        {
            signal: 'asap',
            signal_strategy: 'ema_cross',
            signal_plugins: ['asap', 'csv_signal'],
            strategies: ['ema_cross'],
            symbol_list: 'https://signals.example/symbols.txt',
            timeframe: '15m',
        },
        defaults,
    )

    assert.equal(urlState.signal.asap_use_url, true)
    assert.deepEqual(urlState.signal.asap_symbol_select, [])
    assert.deepEqual(urlState.signal.plugins, [
        { label: 'asap', value: 'asap' },
        { label: 'csv_signal', value: 'csv_signal' },
    ])
    assert.deepEqual(urlState.signal.strategy_plugins, [
        { label: 'ema_cross', value: 'ema_cross' },
    ])
    assert.equal(urlState.signal.strategy_enabled, true)

    const symbolState = buildLoadedConfigState(
        {
            signal: 'asap',
            symbol_list: 'btc, eth/usdt',
            timeframe: '15m',
        },
        defaults,
    )

    assert.equal(symbolState.signal.asap_use_url, false)
    assert.deepEqual(symbolState.signal.asap_symbol_select, [
        'btc',
        'eth/usdt',
    ])
    assert.deepEqual(symbolState.signal.asap_symbol_options, [
        { label: 'btc', value: 'btc' },
        { label: 'eth/usdt', value: 'eth/usdt' },
    ])
})

test('buildLoadedConfigState ignores removed legacy filter shadow payload', () => {
    const defaults = createLoadDefaults()
    const state = buildLoadedConfigState(
        {
            filter: '{"rsi_max":70,"marketcap_cmc_api_key":"legacy"}',
            timeframe: '1h',
        },
        defaults,
    )

    assert.equal(state.filter.rsi, null)
    assert.equal(state.filter.cmc_api_key, null)
})
