import {
    getDefaultHistoryLookbackByTimeframe,
    parseStructuredConfigValue,
    parseSymbolListToArray,
    parseVolumeLimitToNumber,
    toTokenOnlyEntries,
} from './configForm'
import type {
    AutopilotConfigSection,
    CapitalConfigSection,
    DcaConfigSection,
    ExchangeConfigSection,
    FilterConfigSection,
    GeneralConfigSection,
    IndicatorConfigSection,
    MonitoringConfigSection,
    SignalConfigSection,
} from './configSubmitPayload'
import { parseBooleanString, toNumberOrNull } from './validators'

type ConfigOption = {
    label: string
    value: string
}

type ConfigApiResponse = Record<string, unknown>

export interface ConfigLoadDefaults {
    clientTimezone: string
    showAdvancedGeneral: boolean
    advancedWsHealthcheckIntervalMs: number
    advancedWsStaleTimeoutMs: number
    advancedWsReconnectDebounceMs: number
    defaultSymSignalUrl: string
    defaultSymSignalVersion: string
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

export interface LoadedSignalConfigSection extends SignalConfigSection {
    asap_symbol_fetch_error: string | null
    asap_symbol_options: ConfigOption[]
    csvsignal_file_name: string | null
    plugins: ConfigOption[]
    strategy_plugins: ConfigOption[]
    timeframe: string | null
}

export interface LoadedConfigState {
    autopilot: AutopilotConfigSection
    capital: CapitalConfigSection
    dca: DcaConfigSection
    exchange: ExchangeConfigSection
    filter: FilterConfigSection
    general: GeneralConfigSection
    indicator: IndicatorConfigSection
    monitoring: MonitoringConfigSection
    showAdvancedGeneral: boolean
    signal: LoadedSignalConfigSection
}

function toNullableString(value: unknown): string | null {
    if (value === null || value === undefined || value === false) {
        return null
    }

    const normalized = String(value)
    return normalized.length > 0 ? normalized : null
}

function isUrlValue(value: unknown): boolean {
    const normalized = toNullableString(value)
    return normalized ? /^https?:\/\//i.test(normalized.trim()) : false
}

function toConfigOptions(values: unknown): ConfigOption[] {
    if (!Array.isArray(values)) {
        return []
    }

    return values
        .map((value) => toNullableString(value))
        .filter((value): value is string => value !== null)
        .map((value) => ({
            label: value,
            value,
        }))
}

export function buildLoadedConfigState(
    response: ConfigApiResponse,
    defaults: ConfigLoadDefaults,
): LoadedConfigState {
    const signalSettings = parseStructuredConfigValue(response.signal_settings)
    const signalValue = toNullableString(response.signal)
    const signalStrategy = toNullableString(response.signal_strategy)
    const timeframe = toNullableString(response.timeframe)
    const symbolList = toNullableString(response.symbol_list)
    const asapUseUrl = isUrlValue(response.symbol_list)
    const configuredSymbols = asapUseUrl ? [] : parseSymbolListToArray(symbolList)

    let csvsignalMode = 'source'
    let csvsignalSource: string | null = null
    let csvsignalInline: string | null = null

    const csvSourceRaw = signalSettings?.csv_source
    if (csvSourceRaw) {
        const csvSource = String(csvSourceRaw)
        const isInlineCsv = csvSource.includes('\n') && csvSource.includes(';')
        if (isInlineCsv) {
            csvsignalMode = 'inline'
            csvsignalInline = csvSource
        } else {
            csvsignalSource = csvSource
        }
    }

    const general: GeneralConfigSection = {
        timezone: toNullableString(response.timezone) || defaults.clientTimezone,
        debug: parseBooleanString(response.debug) ?? false,
        ws_watchdog_enabled: parseBooleanString(response.ws_watchdog_enabled) ?? true,
        ws_healthcheck_interval_ms:
            toNumberOrNull(response.ws_healthcheck_interval_ms) ??
            defaults.advancedWsHealthcheckIntervalMs,
        ws_stale_timeout_ms:
            toNumberOrNull(response.ws_stale_timeout_ms) ??
            defaults.advancedWsStaleTimeoutMs,
        ws_reconnect_debounce_ms:
            toNumberOrNull(response.ws_reconnect_debounce_ms) ??
            defaults.advancedWsReconnectDebounceMs,
    }

    const exchange: ExchangeConfigSection = {
        name: toNullableString(response.exchange),
        timeframe,
        key: toNullableString(response.key),
        secret: toNullableString(response.secret),
        exchange_hostname: toNullableString(response.exchange_hostname),
        dry_run: parseBooleanString(response.dry_run) ?? true,
        currency: toNullableString(response.currency),
        market: toNullableString(response.market) || 'spot',
        watcher_ohlcv: parseBooleanString(response.watcher_ohlcv) ?? false,
    }
    const dcaEnabled = parseBooleanString(response.dca) ?? false
    const dynamicDca = parseBooleanString(response.dynamic_dca) ?? false

    return {
        general,
        signal: {
            symbol_list: symbolList,
            asap_use_url: asapUseUrl,
            asap_symbol_select: configuredSymbols,
            asap_symbol_fetch_error: null,
            asap_symbol_options: configuredSymbols.map((symbol) => ({
                label: symbol,
                value: symbol,
            })),
            signal: signalValue,
            plugins: toConfigOptions(response.signal_plugins),
            strategy: signalStrategy,
            strategy_enabled: signalStrategy !== null,
            strategy_plugins: toConfigOptions(response.strategies),
            timeframe,
            symsignal_url: signalSettings
                ? String(signalSettings.api_url || defaults.defaultSymSignalUrl)
                : null,
            symsignal_key: signalSettings
                ? String(signalSettings.api_key || '')
                : null,
            symsignal_version: signalSettings
                ? String(
                      signalSettings.api_version || defaults.defaultSymSignalVersion
                  )
                : null,
            symsignal_allowedsignals: Array.isArray(signalSettings?.allowed_signals)
                ? signalSettings.allowed_signals
                : [],
            csvsignal_mode: csvsignalMode,
            csvsignal_source: csvsignalSource,
            csvsignal_inline: csvsignalInline,
            csvsignal_file_name: null,
        },
        filter: {
            rsi: toNumberOrNull(response.rsi_max),
            cmc_api_key: toNullableString(response.marketcap_cmc_api_key),
            denylist: toTokenOnlyEntries(toNullableString(response.pair_denylist)),
            topcoin_limit: toNumberOrNull(response.topcoin_limit),
            volume:
                toNumberOrNull(response.volume) ??
                parseVolumeLimitToNumber(response.volume),
            btc_pulse: parseBooleanString(response.btc_pulse) ?? false,
        },
        exchange,
        dca: {
            enabled: dcaEnabled,
            dynamic: dynamicDca,
            strategy: toNullableString(response.dca_strategy),
            timeframe,
            trailing_tp: toNumberOrNull(response.trailing_tp),
            max_bots: toNumberOrNull(response.max_bots),
            bo: toNumberOrNull(response.bo),
            sell_order_type: toNullableString(response.sell_order_type) || 'market',
            limit_sell_timeout_sec:
                toNumberOrNull(response.limit_sell_timeout_sec) ?? 60,
            limit_sell_fallback_to_market:
                parseBooleanString(response.limit_sell_fallback_to_market) ?? true,
            tp_limit_prearm_enabled:
                parseBooleanString(response.tp_limit_prearm_enabled) ?? false,
            tp_limit_prearm_margin_percent:
                toNumberOrNull(response.tp_limit_prearm_margin_percent) ?? 0.25,
            tp_spike_confirm_enabled:
                parseBooleanString(response.tp_spike_confirm_enabled) ?? false,
            tp_spike_confirm_seconds:
                toNumberOrNull(response.tp_spike_confirm_seconds) ??
                defaults.defaultTpSpikeConfirmSeconds,
            tp_spike_confirm_ticks:
                toNumberOrNull(response.tp_spike_confirm_ticks) ??
                defaults.defaultTpSpikeConfirmTicks,
            so: toNumberOrNull(response.so),
            mstc: toNumberOrNull(response.mstc),
            sos: toNumberOrNull(response.sos),
            ss: toNumberOrNull(response.ss),
            os: toNumberOrNull(response.os),
            trade_safety_order_budget_ratio:
                toNumberOrNull(response.trade_safety_order_budget_ratio) ?? 0.95,
            tp: toNumberOrNull(response.tp),
            sl: toNumberOrNull(response.sl),
        },
        capital: {
            max_fund: toNumberOrNull(response.capital_max_fund),
            reserve_safety_orders:
                parseBooleanString(response.capital_reserve_safety_orders) ?? false,
            budget_buffer_pct:
                dcaEnabled && dynamicDca
                    ? toNumberOrNull(response.capital_budget_buffer_pct) ?? 0
                    : 0,
        },
        autopilot: {
            enabled: parseBooleanString(response.autopilot) ?? false,
            symbol_entry_sizing_enabled:
                parseBooleanString(
                    response.autopilot_symbol_entry_sizing_enabled,
                ) ?? false,
            profit_stretch_enabled:
                parseBooleanString(response.autopilot_profit_stretch_enabled) ??
                false,
            profit_stretch_ratio:
                toNumberOrNull(response.autopilot_profit_stretch_ratio) ??
                defaults.defaultAutopilotProfitStretchRatio,
            profit_stretch_max:
                toNumberOrNull(response.autopilot_profit_stretch_max) ??
                defaults.defaultAutopilotProfitStretchMax,
            base_order_stretch_max_multiplier:
                toNumberOrNull(
                    response.autopilot_base_order_stretch_max_multiplier
                ) ??
                toNumberOrNull(response.autopilot_entry_stretch_max_multiplier) ??
                defaults.defaultAutopilotBaseOrderStretchMaxMultiplier,
            high_mad: toNumberOrNull(response.autopilot_high_mad),
            high_tp: toNumberOrNull(response.autopilot_high_tp),
            high_sl: toNumberOrNull(response.autopilot_high_sl),
            high_sl_timeout: toNumberOrNull(response.autopilot_high_sl_timeout),
            high_threshold: toNumberOrNull(response.autopilot_high_threshold),
            medium_mad: toNumberOrNull(response.autopilot_medium_mad),
            medium_tp: toNumberOrNull(response.autopilot_medium_tp),
            medium_sl: toNumberOrNull(response.autopilot_medium_sl),
            medium_sl_timeout: toNumberOrNull(
                response.autopilot_medium_sl_timeout
            ),
            medium_threshold: toNumberOrNull(response.autopilot_medium_threshold),
            green_phase_enabled:
                parseBooleanString(response.autopilot_green_phase_enabled) ?? false,
            green_phase_ramp_days:
                toNumberOrNull(response.autopilot_green_phase_ramp_days) ??
                defaults.defaultGreenPhaseRampDays,
            green_phase_eval_interval_sec:
                toNumberOrNull(response.autopilot_green_phase_eval_interval_sec) ??
                defaults.defaultGreenPhaseEvalIntervalSec,
            green_phase_window_minutes:
                toNumberOrNull(response.autopilot_green_phase_window_minutes) ??
                defaults.defaultGreenPhaseWindowMinutes,
            green_phase_min_profitable_close_ratio:
                toNumberOrNull(
                    response.autopilot_green_phase_min_profitable_close_ratio
                ) ?? defaults.defaultGreenPhaseMinProfitableCloseRatio,
            green_phase_speed_multiplier:
                toNumberOrNull(response.autopilot_green_phase_speed_multiplier) ??
                defaults.defaultGreenPhaseSpeedMultiplier,
            green_phase_exit_multiplier:
                toNumberOrNull(response.autopilot_green_phase_exit_multiplier) ??
                defaults.defaultGreenPhaseExitMultiplier,
            green_phase_max_extra_deals:
                toNumberOrNull(response.autopilot_green_phase_max_extra_deals) ??
                defaults.defaultGreenPhaseMaxExtraDeals,
            green_phase_confirm_cycles:
                toNumberOrNull(response.autopilot_green_phase_confirm_cycles) ??
                defaults.defaultGreenPhaseConfirmCycles,
            green_phase_release_cycles:
                toNumberOrNull(response.autopilot_green_phase_release_cycles) ??
                defaults.defaultGreenPhaseReleaseCycles,
            green_phase_max_locked_fund_percent:
                toNumberOrNull(
                    response.autopilot_green_phase_max_locked_fund_percent
                ) ?? defaults.defaultGreenPhaseMaxLockedFundPercent,
        },
        monitoring: {
            enabled: parseBooleanString(response.monitoring_enabled) ?? false,
            telegram_bot_token: toNullableString(
                response.monitoring_telegram_bot_token
            ),
            telegram_api_id: toNumberOrNull(response.monitoring_telegram_api_id),
            telegram_api_hash: toNullableString(
                response.monitoring_telegram_api_hash
            ),
            telegram_chat_id: toNullableString(response.monitoring_telegram_chat_id),
            timeout_sec: toNumberOrNull(response.monitoring_timeout_sec) ?? 5,
            retry_count: toNumberOrNull(response.monitoring_retry_count) ?? 1,
        },
        indicator: {
            upnl_housekeeping_interval:
                toNumberOrNull(response.upnl_housekeeping_interval) ?? 0,
            history_lookback_time:
                toNullableString(response.history_lookback_time) ||
                getDefaultHistoryLookbackByTimeframe(timeframe),
        },
        showAdvancedGeneral: defaults.showAdvancedGeneral,
    }
}
