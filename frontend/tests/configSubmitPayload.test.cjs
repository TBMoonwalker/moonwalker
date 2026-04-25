const assert = require('node:assert/strict')
const test = require('node:test')

const { loadFrontendModule } = require('./helpers/loadFrontendModule.cjs')

const { buildConfigSubmitPayload } = loadFrontendModule(
    'src/helpers/configSubmitPayload.ts',
)

function createPayloadDefaults(overrides = {}) {
    return {
        advancedWsHealthcheckIntervalMs: 30000,
        advancedWsStaleTimeoutMs: 45000,
        advancedWsReconnectDebounceMs: 5000,
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

function parseField(payload, key) {
    return payload[key]
}

function createBaseOptions(overrides = {}) {
    const base = {
        general: {
            timezone: 'Europe/Vienna',
            debug: false,
            ws_watchdog_enabled: false,
            ws_healthcheck_interval_ms: null,
            ws_stale_timeout_ms: null,
            ws_reconnect_debounce_ms: null,
        },
        signal: {
            symbol_list: null,
            asap_use_url: false,
            asap_symbol_select: [],
            signal: 'asap',
            strategy: null,
            strategy_enabled: false,
            symsignal_url: null,
            symsignal_key: null,
            symsignal_version: null,
            symsignal_allowedsignals: [],
            csvsignal_mode: 'source',
            csvsignal_source: null,
            csvsignal_inline: null,
        },
        filter: {
            rsi: null,
            cmc_api_key: null,
            denylist: null,
            topcoin_limit: null,
            volume: null,
            btc_pulse: false,
        },
        exchange: {
            name: 'binance',
            timeframe: '1h',
            key: 'key',
            secret: 'secret',
            exchange_hostname: 'api.exchange.test',
            dry_run: true,
            currency: 'usdt',
            market: 'spot',
            watcher_ohlcv: false,
        },
        dca: {
            enabled: true,
            dynamic: false,
            strategy: 'ema_cross',
            timeframe: '1h',
            trailing_tp: null,
            max_bots: 2,
            bo: 20,
            sell_order_type: 'market',
            limit_sell_timeout_sec: 60,
            limit_sell_fallback_to_market: true,
            tp_spike_confirm_enabled: false,
            tp_spike_confirm_seconds: null,
            tp_spike_confirm_ticks: null,
            so: 10,
            mstc: 3,
            sos: 1.5,
            ss: 1.2,
            os: 1.4,
            trade_safety_order_budget_ratio: 0.95,
            tp: 1.8,
            sl: null,
        },
        capital: {
            max_fund: null,
            reserve_safety_orders: true,
            budget_buffer_pct: 0,
        },
        autopilot: {
            enabled: false,
            symbol_entry_sizing_enabled: false,
            profit_stretch_enabled: false,
            profit_stretch_ratio: 0,
            profit_stretch_max: 0,
            entry_stretch_max_multiplier: 1,
            safety_stretch_max_multiplier: 1,
            high_mad: null,
            high_tp: null,
            high_sl: null,
            high_sl_timeout: null,
            high_threshold: null,
            medium_mad: null,
            medium_tp: null,
            medium_sl: null,
            medium_sl_timeout: null,
            medium_threshold: null,
            green_phase_enabled: false,
            green_phase_ramp_days: null,
            green_phase_eval_interval_sec: null,
            green_phase_window_minutes: null,
            green_phase_min_profitable_close_ratio: null,
            green_phase_speed_multiplier: null,
            green_phase_exit_multiplier: null,
            green_phase_max_extra_deals: null,
            green_phase_confirm_cycles: null,
            green_phase_release_cycles: null,
            green_phase_max_locked_fund_percent: null,
        },
        monitoring: {
            enabled: false,
            telegram_bot_token: null,
            telegram_api_id: null,
            telegram_api_hash: null,
            telegram_chat_id: null,
            timeout_sec: 5,
            retry_count: 1,
        },
        indicator: {
            upnl_housekeeping_interval: 7,
            history_lookback_time: null,
        },
        showAdvancedGeneral: true,
        defaults: createPayloadDefaults(),
    }

    return {
        ...base,
        ...overrides,
    }
}

test(
    'buildConfigSubmitPayload keeps CSV signal strategy cleared and applies defaults',
    () => {
        const payload = buildConfigSubmitPayload(
            createBaseOptions({
                signal: {
                    symbol_list: null,
                    asap_use_url: false,
                    asap_symbol_select: [],
                    signal: 'csv_signal',
                    strategy: 'ema_cross',
                    strategy_enabled: true,
                    symsignal_url: null,
                    symsignal_key: null,
                    symsignal_version: null,
                    symsignal_allowedsignals: [],
                    csvsignal_mode: 'inline',
                    csvsignal_source: null,
                    csvsignal_inline: 'pair;side\nBTC/USDT;buy',
                },
                filter: {
                    rsi: null,
                    cmc_api_key: null,
                    denylist: 'btc,eth',
                    topcoin_limit: null,
                    volume: null,
                    btc_pulse: false,
                },
                dca: {
                    enabled: true,
                    dynamic: true,
                    strategy: 'ema_cross',
                    timeframe: '1h',
                    trailing_tp: null,
                    max_bots: 2,
                    bo: 20,
                    sell_order_type: 'market',
                    limit_sell_timeout_sec: 60,
                    limit_sell_fallback_to_market: true,
                    tp_spike_confirm_enabled: false,
                    tp_spike_confirm_seconds: null,
                    tp_spike_confirm_ticks: null,
                    so: 10,
                    mstc: 3,
                    sos: 1.5,
                    ss: 1.2,
                    os: 1.4,
                    trade_safety_order_budget_ratio: 0.95,
                    tp: 1.8,
                    sl: null,
                },
                showAdvancedGeneral: false,
            }),
        )

        assert.deepEqual(parseField(payload, 'signal_strategy'), {
            value: null,
            type: 'str',
        })
        assert.deepEqual(parseField(payload, 'exchange_hostname'), {
            value: 'api.exchange.test',
            type: 'str',
        })
        assert.deepEqual(parseField(payload, 'signal_settings'), {
            value: { csv_source: 'pair;side\nBTC/USDT;buy' },
            type: 'str',
        })
        assert.equal('filter' in payload, false)
        assert.equal(parseField(payload, 'history_lookback_time').value, '180d')
        assert.equal(parseField(payload, 'pair_denylist').value, 'BTC/USDT,ETH/USDT')
        assert.equal(parseField(payload, 'os').value, false)
        assert.equal(
            parseField(payload, 'autopilot_symbol_entry_sizing_enabled').value,
            false,
        )
        assert.deepEqual(parseField(payload, 'capital_max_fund'), {
            value: false,
            type: 'int',
        })
        assert.equal(parseField(payload, 'capital_reserve_safety_orders').value, true)
        assert.equal(parseField(payload, 'capital_budget_buffer_pct').value, 0)
        assert.equal(
            parseField(payload, 'autopilot_profit_stretch_enabled').value,
            false,
        )
    },
)

test('buildConfigSubmitPayload normalizes ASAP symbol selections', () => {
    const payload = buildConfigSubmitPayload(
        createBaseOptions({
            signal: {
                symbol_list: null,
                asap_use_url: false,
                asap_symbol_select: ['btc', 'eth/busd'],
                signal: 'asap',
                strategy: 'ema_cross',
                strategy_enabled: true,
                symsignal_url: null,
                symsignal_key: null,
                symsignal_version: null,
                symsignal_allowedsignals: [],
                csvsignal_mode: 'source',
                csvsignal_source: null,
                csvsignal_inline: null,
            },
        }),
    )

    assert.equal(
        parseField(payload, 'symbol_list').value,
        'BTC/USDT,ETH/BUSD',
    )
    assert.equal(parseField(payload, 'signal_strategy').value, 'ema_cross')
})

test('buildConfigSubmitPayload persists configured capital budget and stretch settings', () => {
    const payload = buildConfigSubmitPayload(
        createBaseOptions({
            capital: {
                max_fund: 250,
                reserve_safety_orders: false,
                budget_buffer_pct: 0.03,
            },
            autopilot: {
                enabled: true,
                symbol_entry_sizing_enabled: true,
                profit_stretch_enabled: true,
                profit_stretch_ratio: 0.5,
                profit_stretch_max: 75,
                entry_stretch_max_multiplier: 2,
                safety_stretch_max_multiplier: 1.5,
                high_mad: null,
                high_tp: null,
                high_sl: null,
                high_sl_timeout: null,
                high_threshold: null,
                medium_mad: null,
                medium_tp: null,
                medium_sl: null,
                medium_sl_timeout: null,
                medium_threshold: null,
                green_phase_enabled: false,
                green_phase_ramp_days: null,
                green_phase_eval_interval_sec: null,
                green_phase_window_minutes: null,
                green_phase_min_profitable_close_ratio: null,
                green_phase_speed_multiplier: null,
                green_phase_exit_multiplier: null,
                green_phase_max_extra_deals: null,
                green_phase_confirm_cycles: null,
                green_phase_release_cycles: null,
                green_phase_max_locked_fund_percent: null,
            },
        }),
    )

    assert.deepEqual(parseField(payload, 'capital_max_fund'), {
        value: 250,
        type: 'int',
    })
    assert.deepEqual(parseField(payload, 'autopilot_max_fund'), {
        value: 250,
        type: 'int',
    })
    assert.deepEqual(parseField(payload, 'capital_reserve_safety_orders'), {
        value: false,
        type: 'bool',
    })
    assert.deepEqual(parseField(payload, 'capital_budget_buffer_pct'), {
        value: 0.03,
        type: 'float',
    })
    assert.deepEqual(parseField(payload, 'autopilot_symbol_entry_sizing_enabled'), {
        value: true,
        type: 'bool',
    })
    assert.deepEqual(parseField(payload, 'autopilot_profit_stretch_enabled'), {
        value: true,
        type: 'bool',
    })
    assert.deepEqual(parseField(payload, 'autopilot_profit_stretch_ratio'), {
        value: 0.5,
        type: 'float',
    })
    assert.deepEqual(parseField(payload, 'autopilot_profit_stretch_max'), {
        value: 75,
        type: 'float',
    })
    assert.deepEqual(parseField(payload, 'autopilot_entry_stretch_max_multiplier'), {
        value: 2,
        type: 'float',
    })
    assert.deepEqual(parseField(payload, 'autopilot_safety_stretch_max_multiplier'), {
        value: 1.5,
        type: 'float',
    })
})
