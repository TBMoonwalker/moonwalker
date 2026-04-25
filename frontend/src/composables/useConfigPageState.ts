import { ref } from 'vue'

import type {
    MixedSelectOption,
    SignalEditorModel,
    StringSelectOption,
} from '../config-editor/types'
import { getAllTimeZones } from '../helpers/timezone'
import type {
    AutopilotConfigSection,
    CapitalConfigSection,
    ConfigSubmitPayloadDefaults,
    DcaConfigSection,
    ExchangeConfigSection,
    FilterConfigSection,
    GeneralConfigSection,
    IndicatorConfigSection,
    MonitoringConfigSection,
    SignalConfigSection,
} from '../helpers/configSubmitPayload'

interface UseConfigPageStateOptions {
    defaults: ConfigSubmitPayloadDefaults
}

const TIMERANGE_OPTIONS: StringSelectOption[] = [
    { label: '1m', value: '1m' },
    { label: '15m', value: '15m' },
    { label: '30m', value: '30m' },
    { label: '1h', value: '1h' },
    { label: '4h', value: '4h' },
    { label: '1d', value: '1d' },
]

const HISTORY_LOOKBACK_OPTIONS: StringSelectOption[] = [
    { label: '30 days (1m default)', value: '30d' },
    { label: '90 days (15m default)', value: '90d' },
    { label: '180 days (1h default)', value: '180d' },
    { label: '1 year (4h default)', value: '1y' },
    { label: '3 years (1d default)', value: '3y' },
]

const EXCHANGE_OPTIONS: StringSelectOption[] = [
    { label: 'Binance', value: 'binance' },
    { label: 'Bybit', value: 'bybit' },
]

const CURRENCY_OPTIONS: StringSelectOption[] = [
    { label: 'USDC', value: 'usdc' },
    { label: 'USDT', value: 'usdt' },
]

const MARKET_OPTIONS: StringSelectOption[] = [{ label: 'Spot', value: 'spot' }]

const SELL_ORDER_TYPE_OPTIONS: StringSelectOption[] = [
    { label: 'Market', value: 'market' },
    { label: 'Limit', value: 'limit' },
]

const SYM_SIGNAL_OPTIONS: MixedSelectOption[] = [
    { label: '12 - SymRank Top 10', value: 12 },
    { label: '2 - SymRank Top 30', value: 2 },
    { label: '11 - SymRank Top 50', value: 11 },
    { label: '1 - SymRank Top 100 Triple Tracker', value: 1 },
    { label: '6 - SymRank Top 100 Quadruple Tracker', value: 6 },
    { label: '7 - SymRank Top 250 Quadruple Tracker', value: 7 },
    { label: '13 - SymScore Super Bullish', value: 13 },
    { label: '22 - SymScore Super Bullish Range', value: 22 },
    { label: '29 - SymScore Super-Hyper Bullish Range', value: 29 },
    { label: '14 - SymScore Hyper Bullish', value: 14 },
    { label: '23 - SymScore Hyper Bullish Range', value: 23 },
    { label: '27 - SymScore Hyper-Ultra Bullish Range', value: 27 },
    { label: '15 - SymScore Ultra Bullish', value: 15 },
    { label: '25 - SymScore Ultra Bullish Range', value: 25 },
    { label: '31 - SymScore Ultra-X-Treme Bullish Range', value: 31 },
    { label: '16 - SymScore X-Treme Bullish', value: 16 },
    { label: '54 - SymScore Neutral', value: 54 },
    { label: '17 - SymScore Super Bearish', value: 17 },
    { label: '21 - SymScore Super Bearish Range', value: 21 },
    { label: '30 - SymScore Super-Hyper Bearish Range', value: 30 },
    { label: '18 - SymScore Hyper Bearish', value: 18 },
    { label: '24 - SymScore Hyper Bearish Range', value: 24 },
    { label: '28 - SymScore Hyper-Ultra Bearish Range', value: 28 },
    { label: '19 - SymScore Ultra Bearish', value: 19 },
    { label: '26 - SymScore Ultra Bearish Range', value: 26 },
    { label: '32 - SymScore Ultra-X-Treme Bearish Range', value: 32 },
    { label: '20 - SymScore X-Treme Bearish', value: 20 },
    { label: '39 - SymSense Super Greed', value: 39 },
    { label: '48 - SymSense Super Greed Range', value: 48 },
    { label: '55 - SymSense Super-Hyper Greed Range', value: 55 },
    { label: '40 - SymSense Hyper Greed', value: 40 },
    { label: '49 - SymSense Hyper Greed Range', value: 49 },
    { label: '56 - SymSense Hyper-Ultra Greed Range', value: 56 },
    { label: '41 - SymSense Ultra Greed', value: 41 },
    { label: '50 - SymSense Ultra Greed Range', value: 50 },
    { label: '57 - SymSense Ultra-X-Treme Greed Range', value: 57 },
    { label: '42 - SymSense X-Treme Greed', value: 42 },
    { label: '43 - SymSense Neutral', value: 43 },
    { label: '44 - SymSense Super Fear', value: 44 },
    { label: '51 - SymSense Super Fear Range', value: 51 },
    { label: '58 - SymSense Super-Hyper Fear Range', value: 58 },
    { label: '45 - SymSense Hyper Fear', value: 45 },
    { label: '52 - SymSense Hyper Fear Range', value: 52 },
    { label: '59 - SymSense Hyper-Ultra Fear Range', value: 59 },
    { label: '46 - SymSense Ultra Fear', value: 46 },
    { label: '53 - SymSense Ultra Fear Range', value: 53 },
    { label: '60 - SymSense Ultra-X-Treme Fear Range', value: 60 },
    { label: '47 - SymSense X-Treme Fear', value: 47 },
    { label: '61 - SymSync 100', value: 61 },
    { label: '62 - SymSync 90', value: 62 },
    { label: '63 - SymSync 80', value: 63 },
    { label: '64 - SymSync 70', value: 64 },
    { label: '65 - SymSync 60', value: 65 },
    { label: '66 - SymSync 50', value: 66 },
    { label: '9 - Super Volatility', value: 9 },
    { label: '33 - Super Volatility Range', value: 33 },
    { label: '36 - Super-Hyper Volatility Range', value: 36 },
    { label: '10 - Super Volatility Double Tracker', value: 10 },
    { label: '3 - Hyper Volatility', value: 3 },
    { label: '34 - Hyper Volatility Range', value: 34 },
    { label: '37 - Hyper-Ultra Volatility Range', value: 37 },
    { label: '8 - Hyper Volatility Double Tracker', value: 8 },
    { label: '4 - Ultra Volatility', value: 4 },
    { label: '35 - Ultra Volatility Range', value: 35 },
    { label: '38 - Ultra-X-Treme Volatility Range', value: 38 },
    { label: '5 - X-Treme Volatility', value: 5 },
]

export function useConfigPageState(options: UseConfigPageStateOptions) {
    const timezone = ref<StringSelectOption[]>([])

    const general = ref<GeneralConfigSection>({
        timezone: null,
        debug: false,
        ws_watchdog_enabled: true,
        ws_healthcheck_interval_ms: options.defaults.advancedWsHealthcheckIntervalMs,
        ws_stale_timeout_ms: options.defaults.advancedWsStaleTimeoutMs,
        ws_reconnect_debounce_ms:
            options.defaults.advancedWsReconnectDebounceMs,
    })

    const signal = ref<SignalEditorModel>({
        symbol_list: null,
        asap_use_url: true,
        asap_symbol_select: [],
        asap_symbol_options: [],
        asap_symbols_loading: false,
        asap_symbol_fetch_error: null,
        signal: null,
        plugins: [],
        strategy: null,
        strategy_enabled: false,
        strategy_plugins: [],
        timeframe: null,
        symsignal_url: null,
        symsignal_key: null,
        symsignal_version: null,
        symsignal_allowedsignals: [],
        csvsignal_mode: 'source',
        csvsignal_source: null,
        csvsignal_inline: null,
        csvsignal_file_name: null,
    })

    const filter = ref<FilterConfigSection>({
        rsi: null,
        cmc_api_key: null,
        denylist: null,
        topcoin_limit: null,
        volume: null,
        btc_pulse: false,
    })

    const exchange = ref<ExchangeConfigSection>({
        name: null,
        timeframe: null,
        key: null,
        secret: null,
        exchange_hostname: null,
        dry_run: true,
        currency: null,
        market: 'spot',
        watcher_ohlcv: false,
    })

    const dca = ref<DcaConfigSection>({
        enabled: false,
        dynamic: false,
        strategy: null,
        timeframe: null,
        trailing_tp: null,
        max_bots: null,
        bo: null,
        sell_order_type: 'market',
        limit_sell_timeout_sec: 60,
        limit_sell_fallback_to_market: true,
        tp_spike_confirm_enabled: false,
        tp_spike_confirm_seconds: options.defaults.defaultTpSpikeConfirmSeconds,
        tp_spike_confirm_ticks: options.defaults.defaultTpSpikeConfirmTicks,
        so: null,
        mstc: null,
        sos: null,
        ss: null,
        os: null,
        trade_safety_order_budget_ratio: 0.95,
        tp: null,
        sl: null,
    })

    const capital = ref<CapitalConfigSection>({
        max_fund: null,
        reserve_safety_orders: true,
        budget_buffer_pct: 0,
    })

    const autopilot = ref<AutopilotConfigSection>({
        enabled: false,
        symbol_entry_sizing_enabled: false,
        profit_stretch_enabled: false,
        profit_stretch_ratio: options.defaults.defaultAutopilotProfitStretchRatio,
        profit_stretch_max: options.defaults.defaultAutopilotProfitStretchMax,
        entry_stretch_max_multiplier:
            options.defaults.defaultAutopilotEntryStretchMaxMultiplier,
        safety_stretch_max_multiplier:
            options.defaults.defaultAutopilotSafetyStretchMaxMultiplier,
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
        green_phase_ramp_days: options.defaults.defaultGreenPhaseRampDays,
        green_phase_eval_interval_sec:
            options.defaults.defaultGreenPhaseEvalIntervalSec,
        green_phase_window_minutes: options.defaults.defaultGreenPhaseWindowMinutes,
        green_phase_min_profitable_close_ratio:
            options.defaults.defaultGreenPhaseMinProfitableCloseRatio,
        green_phase_speed_multiplier:
            options.defaults.defaultGreenPhaseSpeedMultiplier,
        green_phase_exit_multiplier:
            options.defaults.defaultGreenPhaseExitMultiplier,
        green_phase_max_extra_deals:
            options.defaults.defaultGreenPhaseMaxExtraDeals,
        green_phase_confirm_cycles:
            options.defaults.defaultGreenPhaseConfirmCycles,
        green_phase_release_cycles:
            options.defaults.defaultGreenPhaseReleaseCycles,
        green_phase_max_locked_fund_percent:
            options.defaults.defaultGreenPhaseMaxLockedFundPercent,
    })

    const monitoring = ref<MonitoringConfigSection>({
        enabled: false,
        telegram_bot_token: null,
        telegram_api_id: null,
        telegram_api_hash: null,
        telegram_chat_id: null,
        timeout_sec: 5,
        retry_count: 1,
    })

    const indicator = ref<IndicatorConfigSection>({
        upnl_housekeeping_interval: 0,
        history_lookback_time: null,
    })

    function initializeTimezoneOptions(clientTimezone: string): void {
        timezone.value = getAllTimeZones()
        if (!timezone.value.some((timezoneOption) => timezoneOption.value === clientTimezone)) {
            timezone.value.unshift({
                label: clientTimezone,
                value: clientTimezone,
            })
        }
    }

    function resetSignalStrategySelection(): void {
        signal.value.strategy_enabled = false
        signal.value.strategy = null
    }

    return {
        autopilot,
        capital,
        currency: CURRENCY_OPTIONS,
        dca,
        exchange,
        exchanges: EXCHANGE_OPTIONS,
        filter,
        general,
        historyLookbackOptions: HISTORY_LOOKBACK_OPTIONS,
        indicator,
        initializeTimezoneOptions,
        market: MARKET_OPTIONS,
        monitoring,
        resetSignalStrategySelection,
        sellOrderTypeOptions: SELL_ORDER_TYPE_OPTIONS,
        signal,
        symsignals: SYM_SIGNAL_OPTIONS,
        timerange: TIMERANGE_OPTIONS,
        timezone,
    }
}
