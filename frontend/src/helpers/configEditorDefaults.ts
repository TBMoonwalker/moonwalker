import { MOONWALKER_API_ORIGIN } from '../config'
import type { ConfigSubmitPayloadDefaults } from './configSubmitPayload'

export const CONFIG_ADVANCED_GENERAL_PREFERENCE_KEY =
    'moonwalker.config.showAdvancedGeneral'
export const CONFIG_DEFAULT_SYMSIGNAL_URL = 'https://stream.3cqs.com'
export const CONFIG_DEFAULT_SYMSIGNAL_VERSION = '3.0.1'

const ADVANCED_WS_HEALTHCHECK_INTERVAL_MS = 5000
const ADVANCED_WS_STALE_TIMEOUT_MS = 20000
const ADVANCED_WS_RECONNECT_DEBOUNCE_MS = 2000
const DEFAULT_TP_SPIKE_CONFIRM_SECONDS = 3
const DEFAULT_TP_SPIKE_CONFIRM_TICKS = 0
const DEFAULT_GREEN_PHASE_RAMP_DAYS = 30
const DEFAULT_GREEN_PHASE_EVAL_INTERVAL_SEC = 60
const DEFAULT_GREEN_PHASE_WINDOW_MINUTES = 60
const DEFAULT_GREEN_PHASE_MIN_PROFITABLE_CLOSE_RATIO = 0.8
const DEFAULT_GREEN_PHASE_SPEED_MULTIPLIER = 1.5
const DEFAULT_GREEN_PHASE_EXIT_MULTIPLIER = 1.15
const DEFAULT_GREEN_PHASE_MAX_EXTRA_DEALS = 2
const DEFAULT_GREEN_PHASE_CONFIRM_CYCLES = 2
const DEFAULT_GREEN_PHASE_RELEASE_CYCLES = 4
const DEFAULT_GREEN_PHASE_MAX_LOCKED_FUND_PERCENT = 85
const DEFAULT_AUTOPILOT_PROFIT_STRETCH_RATIO = 0
const DEFAULT_AUTOPILOT_PROFIT_STRETCH_MAX = 0
const DEFAULT_AUTOPILOT_ENTRY_STRETCH_MAX_MULTIPLIER = 1
const DEFAULT_AUTOPILOT_SAFETY_STRETCH_MAX_MULTIPLIER = 1

export const CONFIG_SUBMIT_PAYLOAD_DEFAULTS: ConfigSubmitPayloadDefaults = {
    advancedWsHealthcheckIntervalMs: ADVANCED_WS_HEALTHCHECK_INTERVAL_MS,
    advancedWsStaleTimeoutMs: ADVANCED_WS_STALE_TIMEOUT_MS,
    advancedWsReconnectDebounceMs: ADVANCED_WS_RECONNECT_DEBOUNCE_MS,
    defaultTpSpikeConfirmSeconds: DEFAULT_TP_SPIKE_CONFIRM_SECONDS,
    defaultTpSpikeConfirmTicks: DEFAULT_TP_SPIKE_CONFIRM_TICKS,
    defaultGreenPhaseRampDays: DEFAULT_GREEN_PHASE_RAMP_DAYS,
    defaultGreenPhaseEvalIntervalSec: DEFAULT_GREEN_PHASE_EVAL_INTERVAL_SEC,
    defaultGreenPhaseWindowMinutes: DEFAULT_GREEN_PHASE_WINDOW_MINUTES,
    defaultGreenPhaseMinProfitableCloseRatio:
        DEFAULT_GREEN_PHASE_MIN_PROFITABLE_CLOSE_RATIO,
    defaultGreenPhaseSpeedMultiplier: DEFAULT_GREEN_PHASE_SPEED_MULTIPLIER,
    defaultGreenPhaseExitMultiplier: DEFAULT_GREEN_PHASE_EXIT_MULTIPLIER,
    defaultGreenPhaseMaxExtraDeals: DEFAULT_GREEN_PHASE_MAX_EXTRA_DEALS,
    defaultGreenPhaseConfirmCycles: DEFAULT_GREEN_PHASE_CONFIRM_CYCLES,
    defaultGreenPhaseReleaseCycles: DEFAULT_GREEN_PHASE_RELEASE_CYCLES,
    defaultGreenPhaseMaxLockedFundPercent:
        DEFAULT_GREEN_PHASE_MAX_LOCKED_FUND_PERCENT,
    defaultAutopilotProfitStretchRatio:
        DEFAULT_AUTOPILOT_PROFIT_STRETCH_RATIO,
    defaultAutopilotProfitStretchMax: DEFAULT_AUTOPILOT_PROFIT_STRETCH_MAX,
    defaultAutopilotEntryStretchMaxMultiplier:
        DEFAULT_AUTOPILOT_ENTRY_STRETCH_MAX_MULTIPLIER,
    defaultAutopilotSafetyStretchMaxMultiplier:
        DEFAULT_AUTOPILOT_SAFETY_STRETCH_MAX_MULTIPLIER,
}

export function getClientTimezone(): string {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
}

export function buildMoonwalkerApiUrl(path: string): string {
    return new URL(path, MOONWALKER_API_ORIGIN).toString()
}
