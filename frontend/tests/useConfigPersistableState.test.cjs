const assert = require('node:assert/strict')
const test = require('node:test')

const { ref } = require('vue')

const { loadFrontendModule } = require('./helpers/loadFrontendModule.cjs')

const { useConfigPersistableState } = loadFrontendModule(
    'src/composables/useConfigPersistableState.ts',
)

function createPersistableStateOptions() {
    return {
        general: ref({
            timezone: 'Europe/Vienna',
            debug: false,
            ws_watchdog_enabled: true,
            ws_healthcheck_interval_ms: 30000,
            ws_stale_timeout_ms: 45000,
            ws_reconnect_debounce_ms: 5000,
        }),
        signal: ref({
            symbol_list: 'BTC/USDT',
            asap_use_url: false,
            asap_symbol_select: ['BTC/USDT'],
            asap_symbol_fetch_error: null,
            asap_symbol_options: [
                { label: 'BTC/USDT', value: 'BTC/USDT' },
            ],
            signal: 'asap',
            plugins: [{ label: 'asap', value: 'asap' }],
            strategy: 'ema_cross',
            strategy_enabled: true,
            strategy_plugins: [
                { label: 'ema_cross', value: 'ema_cross' },
            ],
            timeframe: '1h',
            symsignal_url: null,
            symsignal_key: null,
            symsignal_version: null,
            symsignal_allowedsignals: [],
            csvsignal_mode: 'source',
            csvsignal_source: null,
            csvsignal_inline: null,
            csvsignal_file_name: null,
        }),
        filter: ref({
            rsi: null,
            cmc_api_key: null,
            denylist: null,
            topcoin_limit: null,
            volume: null,
            btc_pulse: false,
        }),
        exchange: ref({
            name: 'binance',
            timeframe: '1h',
            key: 'key',
            secret: 'secret',
            exchange_hostname: null,
            dry_run: true,
            currency: 'USDT',
            market: 'spot',
            watcher_ohlcv: false,
        }),
        dca: ref({
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
            tp_spike_confirm_seconds: 20,
            tp_spike_confirm_ticks: 5,
            so: 10,
            mstc: 3,
            sos: 1.5,
            ss: 1.2,
            os: 1.4,
            trade_safety_order_budget_ratio: 0.95,
            tp: 1.8,
            sl: null,
        }),
        autopilot: ref({
            enabled: false,
            symbol_entry_sizing_enabled: false,
            max_fund: null,
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
            green_phase_ramp_days: 7,
            green_phase_eval_interval_sec: 600,
            green_phase_window_minutes: 90,
            green_phase_min_profitable_close_ratio: 0.35,
            green_phase_speed_multiplier: 1.5,
            green_phase_exit_multiplier: 1.1,
            green_phase_max_extra_deals: 4,
            green_phase_confirm_cycles: 3,
            green_phase_release_cycles: 2,
            green_phase_max_locked_fund_percent: 55,
        }),
        monitoring: ref({
            enabled: false,
            telegram_bot_token: null,
            telegram_api_id: null,
            telegram_api_hash: null,
            telegram_chat_id: null,
            timeout_sec: 5,
            retry_count: 1,
        }),
        indicator: ref({
            upnl_housekeeping_interval: 7,
            history_lookback_time: '180d',
        }),
    }
}

test('useConfigPersistableState ignores runtime-only signal fields', () => {
    const options = createPersistableStateOptions()
    const tracking = useConfigPersistableState(options)

    tracking.syncBaselineState()

    options.signal.value.asap_symbol_fetch_error = 'fetch failed'
    options.signal.value.asap_symbol_options = [
        { label: 'ETH/USDT', value: 'ETH/USDT' },
    ]
    options.signal.value.plugins = [
        { label: 'csv_signal', value: 'csv_signal' },
    ]

    assert.equal(tracking.isDirty.value, false)
    assert.deepEqual(tracking.changedSections.value, [])
})

test('useConfigPersistableState tracks persistable section changes by label', () => {
    const options = createPersistableStateOptions()
    const tracking = useConfigPersistableState(options)

    tracking.syncBaselineState()
    options.signal.value.csvsignal_source = 'signals.csv'

    assert.equal(tracking.isDirty.value, true)
    assert.deepEqual(tracking.changedSections.value, ['signal'])
    assert.deepEqual(tracking.changedSectionLabels.value, ['Signal'])

    tracking.syncBaselineState()
    options.signal.value.csvsignal_file_name = 'signals.csv'

    assert.deepEqual(tracking.changedSections.value, [])
    assert.deepEqual(tracking.changedSectionLabels.value, [])
})
