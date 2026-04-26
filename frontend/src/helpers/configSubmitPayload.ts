import {
    type ConfigUpdatePayload,
    buildSignalSettingsValue,
    buildVolumeConfig,
    getDefaultHistoryLookbackByTimeframe,
    normalizePairEntries,
    serializeConfigValue,
    toNullableConfigString,
} from './configForm'

export interface GeneralConfigSection {
    timezone: string | null
    debug: boolean
    ws_watchdog_enabled: boolean
    ws_healthcheck_interval_ms: number | null
    ws_stale_timeout_ms: number | null
    ws_reconnect_debounce_ms: number | null
}

export interface SignalConfigSection {
    symbol_list: string | null
    asap_use_url: boolean
    asap_symbol_select: string[]
    signal: string | null
    strategy: string | null
    strategy_enabled: boolean
    symsignal_url: string | null
    symsignal_key: string | null
    symsignal_version: string | null
    symsignal_allowedsignals: unknown[]
    csvsignal_mode: string | null
    csvsignal_source: string | null
    csvsignal_inline: string | null
}

export interface FilterConfigSection {
    rsi: number | null
    cmc_api_key: string | null
    denylist: string | null
    topcoin_limit: number | null
    volume: number | null
    btc_pulse: boolean
}

export interface ExchangeConfigSection {
    name: string | null
    timeframe: string | null
    key: string | null
    secret: string | null
    exchange_hostname: string | null
    dry_run: boolean
    currency: string | null
    market: string | null
    watcher_ohlcv: boolean
}

export interface DcaConfigSection {
    enabled: boolean
    dynamic: boolean
    strategy: string | null
    timeframe: string | null
    trailing_tp: number | null
    max_bots: number | null
    bo: number | null
    sell_order_type: string | null
    limit_sell_timeout_sec: number | null
    limit_sell_fallback_to_market: boolean
    tp_limit_prearm_enabled: boolean
    tp_limit_prearm_margin_percent: number | null
    tp_spike_confirm_enabled: boolean
    tp_spike_confirm_seconds: number | null
    tp_spike_confirm_ticks: number | null
    so: number | null
    mstc: number | null
    sos: number | null
    ss: number | null
    os: number | null
    trade_safety_order_budget_ratio: number | null
    tp: number | null
    sl: number | null
}

export interface CapitalConfigSection {
    max_fund: number | null
    reserve_safety_orders: boolean
    budget_buffer_pct: number | null
}

export interface AutopilotConfigSection {
    enabled: boolean
    symbol_entry_sizing_enabled: boolean
    profit_stretch_enabled: boolean
    profit_stretch_ratio: number | null
    profit_stretch_max: number | null
    base_order_stretch_max_multiplier: number | null
    high_mad: number | null
    high_tp: number | null
    high_sl: number | null
    high_sl_timeout: number | null
    high_threshold: number | null
    medium_mad: number | null
    medium_tp: number | null
    medium_sl: number | null
    medium_sl_timeout: number | null
    medium_threshold: number | null
    green_phase_enabled: boolean
    green_phase_ramp_days: number | null
    green_phase_eval_interval_sec: number | null
    green_phase_window_minutes: number | null
    green_phase_min_profitable_close_ratio: number | null
    green_phase_speed_multiplier: number | null
    green_phase_exit_multiplier: number | null
    green_phase_max_extra_deals: number | null
    green_phase_confirm_cycles: number | null
    green_phase_release_cycles: number | null
    green_phase_max_locked_fund_percent: number | null
}

export interface MonitoringConfigSection {
    enabled: boolean
    telegram_bot_token: string | null
    telegram_api_id: number | null
    telegram_api_hash: string | null
    telegram_chat_id: string | null
    timeout_sec: number | null
    retry_count: number | null
}

export interface IndicatorConfigSection {
    upnl_housekeeping_interval: number | null
    history_lookback_time: string | null
}

export interface ConfigSubmitPayloadDefaults {
    advancedWsHealthcheckIntervalMs: number
    advancedWsStaleTimeoutMs: number
    advancedWsReconnectDebounceMs: number
    defaultTpSpikeConfirmSeconds: number
    defaultTpSpikeConfirmTicks: number
    defaultGreenPhaseRampDays: number
    defaultGreenPhaseEvalIntervalSec: number
    defaultGreenPhaseWindowMinutes: number
    defaultGreenPhaseMinProfitableCloseRatio: number
    defaultGreenPhaseSpeedMultiplier: number
    defaultGreenPhaseExitMultiplier: number
    defaultGreenPhaseMaxExtraDeals: number
    defaultGreenPhaseConfirmCycles: number
    defaultGreenPhaseReleaseCycles: number
    defaultGreenPhaseMaxLockedFundPercent: number
    defaultAutopilotProfitStretchRatio: number
    defaultAutopilotProfitStretchMax: number
    defaultAutopilotBaseOrderStretchMaxMultiplier: number
}

export interface BuildConfigSubmitPayloadOptions {
    general: GeneralConfigSection
    signal: SignalConfigSection
    filter: FilterConfigSection
    exchange: ExchangeConfigSection
    dca: DcaConfigSection
    capital: CapitalConfigSection
    autopilot: AutopilotConfigSection
    monitoring: MonitoringConfigSection
    indicator: IndicatorConfigSection
    showAdvancedGeneral: boolean
    defaults: ConfigSubmitPayloadDefaults
}

export type ConfigSubmitPayload = Record<string, ConfigUpdatePayload>

export function buildConfigSubmitPayload(
    options: BuildConfigSubmitPayloadOptions,
): ConfigSubmitPayload {
    const {
        general,
        signal,
        filter,
        exchange,
        dca,
        capital,
        autopilot,
        monitoring,
        indicator,
        defaults,
    } = options

    const quoteCurrency = String(exchange.currency || 'USDT').toUpperCase()
    const normalizedSymbolList =
        signal.signal === 'asap'
            ? normalizePairEntries(
                  signal.asap_use_url
                      ? signal.symbol_list
                      : signal.asap_symbol_select.join(','),
                  quoteCurrency,
              )
            : null
    const normalizedDenyList = normalizePairEntries(filter.denylist, quoteCurrency)

    return {
        timezone: serializeConfigValue(
            toNullableConfigString(general.timezone),
            'str',
        ),
        debug: serializeConfigValue(general.debug || false, 'bool'),
        ws_watchdog_enabled: serializeConfigValue(
            general.ws_watchdog_enabled ?? true,
            'bool',
        ),
        ws_healthcheck_interval_ms: serializeConfigValue(
            general.ws_healthcheck_interval_ms ??
                defaults.advancedWsHealthcheckIntervalMs,
            'int',
        ),
        ws_stale_timeout_ms: serializeConfigValue(
            general.ws_stale_timeout_ms ?? defaults.advancedWsStaleTimeoutMs,
            'int',
        ),
        ws_reconnect_debounce_ms: serializeConfigValue(
            general.ws_reconnect_debounce_ms ??
                defaults.advancedWsReconnectDebounceMs,
            'int',
        ),
        signal: serializeConfigValue(toNullableConfigString(signal.signal), 'str'),
        signal_strategy: serializeConfigValue(
            signal.signal === 'csv_signal'
                ? null
                : signal.strategy_enabled
                  ? toNullableConfigString(signal.strategy)
                  : null,
            'str',
        ),
        signal_settings: serializeConfigValue(
            buildSignalSettingsValue({
                signal: signal.signal,
                symsignal_url: signal.symsignal_url,
                symsignal_key: signal.symsignal_key,
                symsignal_version: signal.symsignal_version,
                symsignal_allowedsignals: signal.symsignal_allowedsignals,
                csvsignal_mode: signal.csvsignal_mode,
                csvsignal_source: signal.csvsignal_source,
                csvsignal_inline: signal.csvsignal_inline,
            }),
            'str',
        ),
        symbol_list: serializeConfigValue(normalizedSymbolList, 'str'),
        rsi_max: serializeConfigValue(filter.rsi ?? false, 'float'),
        marketcap_cmc_api_key: serializeConfigValue(
            toNullableConfigString(filter.cmc_api_key),
            'str',
        ),
        volume: serializeConfigValue(buildVolumeConfig(filter.volume), 'str'),
        pair_denylist: serializeConfigValue(normalizedDenyList, 'str'),
        topcoin_limit: serializeConfigValue(filter.topcoin_limit || false, 'int'),
        btc_pulse: serializeConfigValue(filter.btc_pulse || false, 'bool'),
        exchange: serializeConfigValue(toNullableConfigString(exchange.name), 'str'),
        timeframe: serializeConfigValue(
            toNullableConfigString(exchange.timeframe),
            'str',
        ),
        key: serializeConfigValue(toNullableConfigString(exchange.key), 'str'),
        secret: serializeConfigValue(toNullableConfigString(exchange.secret), 'str'),
        exchange_hostname: serializeConfigValue(
            toNullableConfigString(exchange.exchange_hostname),
            'str',
        ),
        dry_run: serializeConfigValue(exchange.dry_run || false, 'bool'),
        currency: serializeConfigValue(
            toNullableConfigString(exchange.currency),
            'str',
        ),
        market: serializeConfigValue(toNullableConfigString(exchange.market), 'str'),
        watcher_ohlcv: serializeConfigValue(exchange.watcher_ohlcv || false, 'bool'),
        dca: serializeConfigValue(dca.enabled || false, 'bool'),
        dynamic_dca: serializeConfigValue(dca.dynamic || false, 'bool'),
        dca_strategy: serializeConfigValue(
            toNullableConfigString(dca.strategy),
            'str',
        ),
        trailing_tp: serializeConfigValue(dca.trailing_tp || false, 'float'),
        max_bots: serializeConfigValue(dca.max_bots || false, 'int'),
        bo: serializeConfigValue(dca.bo || false, 'int'),
        sell_order_type: serializeConfigValue(
            toNullableConfigString(dca.sell_order_type) || 'market',
            'str',
        ),
        limit_sell_timeout_sec: serializeConfigValue(
            dca.limit_sell_timeout_sec ?? 60,
            'int',
        ),
        limit_sell_fallback_to_market: serializeConfigValue(
            dca.limit_sell_fallback_to_market ?? true,
            'bool',
        ),
        tp_limit_prearm_enabled: serializeConfigValue(
            dca.tp_limit_prearm_enabled ?? false,
            'bool',
        ),
        tp_limit_prearm_margin_percent: serializeConfigValue(
            dca.tp_limit_prearm_margin_percent ?? 0.25,
            'float',
        ),
        tp_spike_confirm_enabled: serializeConfigValue(
            dca.tp_spike_confirm_enabled ?? false,
            'bool',
        ),
        tp_spike_confirm_seconds: serializeConfigValue(
            dca.tp_spike_confirm_seconds ??
                defaults.defaultTpSpikeConfirmSeconds,
            'float',
        ),
        tp_spike_confirm_ticks: serializeConfigValue(
            dca.tp_spike_confirm_ticks ?? defaults.defaultTpSpikeConfirmTicks,
            'int',
        ),
        so: serializeConfigValue(dca.so || false, 'int'),
        mstc: serializeConfigValue(dca.mstc || false, 'int'),
        sos: serializeConfigValue(dca.sos || false, 'float'),
        ss: serializeConfigValue(dca.ss || false, 'float'),
        os: serializeConfigValue(
            dca.dynamic ? false : (dca.os || false),
            'float',
        ),
        trade_safety_order_budget_ratio: serializeConfigValue(
            dca.trade_safety_order_budget_ratio ?? 0.95,
            'float',
        ),
        tp: serializeConfigValue(dca.tp || false, 'float'),
        sl: serializeConfigValue(dca.sl || false, 'float'),
        autopilot: serializeConfigValue(autopilot.enabled || false, 'bool'),
        autopilot_symbol_entry_sizing_enabled: serializeConfigValue(
            autopilot.symbol_entry_sizing_enabled ?? false,
            'bool',
        ),
        capital_max_fund: serializeConfigValue(
            capital.max_fund || false,
            'int',
        ),
        autopilot_max_fund: serializeConfigValue(
            capital.max_fund || false,
            'int',
        ),
        capital_reserve_safety_orders: serializeConfigValue(
            capital.reserve_safety_orders ?? false,
            'bool',
        ),
        capital_budget_buffer_pct: serializeConfigValue(
            capital.budget_buffer_pct ?? 0,
            'float',
        ),
        autopilot_profit_stretch_enabled: serializeConfigValue(
            autopilot.profit_stretch_enabled ?? false,
            'bool',
        ),
        autopilot_profit_stretch_ratio: serializeConfigValue(
            autopilot.profit_stretch_ratio ??
                defaults.defaultAutopilotProfitStretchRatio,
            'float',
        ),
        autopilot_profit_stretch_max: serializeConfigValue(
            autopilot.profit_stretch_max ??
                defaults.defaultAutopilotProfitStretchMax,
            'float',
        ),
        autopilot_base_order_stretch_max_multiplier: serializeConfigValue(
            autopilot.base_order_stretch_max_multiplier ??
                defaults.defaultAutopilotBaseOrderStretchMaxMultiplier,
            'float',
        ),
        autopilot_high_mad: serializeConfigValue(
            autopilot.high_mad || false,
            'int',
        ),
        autopilot_high_tp: serializeConfigValue(
            autopilot.high_tp || false,
            'float',
        ),
        autopilot_high_sl: serializeConfigValue(
            autopilot.high_sl || false,
            'float',
        ),
        autopilot_high_sl_timeout: serializeConfigValue(
            autopilot.high_sl_timeout || false,
            'int',
        ),
        autopilot_high_threshold: serializeConfigValue(
            autopilot.high_threshold || false,
            'int',
        ),
        autopilot_medium_mad: serializeConfigValue(
            autopilot.medium_mad || false,
            'int',
        ),
        autopilot_medium_tp: serializeConfigValue(
            autopilot.medium_tp || false,
            'float',
        ),
        autopilot_medium_sl: serializeConfigValue(
            autopilot.medium_sl || false,
            'float',
        ),
        autopilot_medium_sl_timeout: serializeConfigValue(
            autopilot.medium_sl_timeout || false,
            'int',
        ),
        autopilot_medium_threshold: serializeConfigValue(
            autopilot.medium_threshold || false,
            'int',
        ),
        autopilot_green_phase_enabled: serializeConfigValue(
            autopilot.green_phase_enabled ?? false,
            'bool',
        ),
        autopilot_green_phase_ramp_days: serializeConfigValue(
            autopilot.green_phase_ramp_days ??
                defaults.defaultGreenPhaseRampDays,
            'int',
        ),
        autopilot_green_phase_eval_interval_sec: serializeConfigValue(
            autopilot.green_phase_eval_interval_sec ??
                defaults.defaultGreenPhaseEvalIntervalSec,
            'int',
        ),
        autopilot_green_phase_window_minutes: serializeConfigValue(
            autopilot.green_phase_window_minutes ??
                defaults.defaultGreenPhaseWindowMinutes,
            'int',
        ),
        autopilot_green_phase_min_profitable_close_ratio: serializeConfigValue(
            autopilot.green_phase_min_profitable_close_ratio ??
                defaults.defaultGreenPhaseMinProfitableCloseRatio,
            'float',
        ),
        autopilot_green_phase_speed_multiplier: serializeConfigValue(
            autopilot.green_phase_speed_multiplier ??
                defaults.defaultGreenPhaseSpeedMultiplier,
            'float',
        ),
        autopilot_green_phase_exit_multiplier: serializeConfigValue(
            autopilot.green_phase_exit_multiplier ??
                defaults.defaultGreenPhaseExitMultiplier,
            'float',
        ),
        autopilot_green_phase_max_extra_deals: serializeConfigValue(
            autopilot.green_phase_max_extra_deals ??
                defaults.defaultGreenPhaseMaxExtraDeals,
            'int',
        ),
        autopilot_green_phase_confirm_cycles: serializeConfigValue(
            autopilot.green_phase_confirm_cycles ??
                defaults.defaultGreenPhaseConfirmCycles,
            'int',
        ),
        autopilot_green_phase_release_cycles: serializeConfigValue(
            autopilot.green_phase_release_cycles ??
                defaults.defaultGreenPhaseReleaseCycles,
            'int',
        ),
        autopilot_green_phase_max_locked_fund_percent: serializeConfigValue(
            autopilot.green_phase_max_locked_fund_percent ??
                defaults.defaultGreenPhaseMaxLockedFundPercent,
            'float',
        ),
        monitoring_enabled: serializeConfigValue(monitoring.enabled || false, 'bool'),
        monitoring_telegram_api_id: serializeConfigValue(
            monitoring.telegram_api_id || false,
            'int',
        ),
        monitoring_telegram_api_hash: serializeConfigValue(
            toNullableConfigString(monitoring.telegram_api_hash),
            'str',
        ),
        monitoring_telegram_bot_token: serializeConfigValue(
            toNullableConfigString(monitoring.telegram_bot_token),
            'str',
        ),
        monitoring_telegram_chat_id: serializeConfigValue(
            toNullableConfigString(monitoring.telegram_chat_id),
            'str',
        ),
        monitoring_timeout_sec: serializeConfigValue(
            monitoring.timeout_sec ?? 5,
            'int',
        ),
        monitoring_retry_count: serializeConfigValue(
            monitoring.retry_count ?? 1,
            'int',
        ),
        upnl_housekeeping_interval: serializeConfigValue(
            indicator.upnl_housekeeping_interval ?? false,
            'int',
        ),
        history_lookback_time: serializeConfigValue(
            toNullableConfigString(indicator.history_lookback_time) ||
                getDefaultHistoryLookbackByTimeframe(exchange.timeframe),
            'str',
        ),
    }
}
