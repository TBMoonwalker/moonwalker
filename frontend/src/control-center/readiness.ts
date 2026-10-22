import { resolveControlCenterBlocker } from './blockers'
import { deriveSignalModeBlockers } from './signalMode'
import { getTaskPresentation } from './taskRegistry'
import {
    isDynamicTradeMode,
    normalizeTradeMode,
} from '../helpers/tradeLifecycle'
import type {
    ControlCenterBlocker,
    ControlCenterMode,
    ControlCenterReadiness,
    SharedConfigPayload,
} from './types'

function hasRequiredValue(value: unknown): boolean {
    if (value === null || value === undefined) {
        return false
    }
    if (typeof value === 'string') {
        const normalized = value.trim().toLowerCase()
        return normalized.length > 0 && normalized !== 'false'
    }
    if (typeof value === 'boolean') {
        return true
    }
    if (typeof value === 'number') {
        return Number.isFinite(value)
    }
    if (Array.isArray(value)) {
        return value.length > 0
    }
    return true
}

function hasPositiveNumber(value: unknown): boolean {
    const numericValue =
        typeof value === 'number' ? value : Number.parseFloat(String(value ?? ''))
    return Number.isFinite(numericValue) && numericValue > 0
}

function getTradeMode(config: SharedConfigPayload): string {
    return normalizeTradeMode(config.trade_mode)
}

function collectAlwaysRequiredBlockers(
    config: SharedConfigPayload,
): ControlCenterBlocker[] {
    const requiredKeys: Array<[string, string, string]> = [
        ['timezone', 'Timezone missing', 'Choose the operating timezone for this Moonwalker instance.'],
        ['signal', 'Signal source missing', 'Choose how Moonwalker should receive trade signals.'],
        ['exchange', 'Exchange missing', 'Choose the exchange connection Moonwalker should use.'],
        ['timeframe', 'Timeframe missing', 'Choose the primary trading timeframe.'],
        ['key', 'Exchange key missing', 'Add the exchange API key for this instance.'],
        ['secret', 'Exchange secret missing', 'Add the exchange API secret for this instance.'],
        ['currency', 'Quote currency missing', 'Choose the quote currency Moonwalker should trade against.'],
        ['max_bots', 'Max bots missing', 'Set how many bots may run in parallel during dry run.'],
        ['bo', 'Base order missing', 'Set the base order amount for a safe dry-run configuration.'],
        ['tp', 'Take profit missing', 'Set the take profit target before activating trades.'],
        [
            'capital_max_fund',
            'Global max fund missing',
            'Set the global capital cap before Moonwalker can admit buy orders.',
        ],
        [
            'history_lookback_time',
            'History window missing',
            'Set the history lookback window so indicators can initialize reliably.',
        ],
    ]

    return requiredKeys.filter(([key]) => config.trade_mode !== 'accumulation' || !['bo', 'tp'].includes(key)).flatMap(([key, title, description]) =>
        (key === 'capital_max_fund'
            ? hasPositiveNumber(config[key])
            : hasRequiredValue(config[key]))
            ? []
            : [resolveControlCenterBlocker(key, description, title)],
    )
}

function collectDcaBlockers(config: SharedConfigPayload): ControlCenterBlocker[] {
    if (normalizeTradeMode(config.trade_mode) === 'unsupported') return [resolveControlCenterBlocker('trade_mode', 'Select a supported entry mode before trading.', 'Unknown trade mode')]
    if (config.trade_mode === 'accumulation') {
        const blockers: ControlCenterBlocker[] = []
        if (config.accumulation_available !== true) blockers.push(resolveControlCenterBlocker('trade_mode', 'Accumulation is unavailable in this release.', 'Accumulation unavailable'))
        if (!config.dca) blockers.push(resolveControlCenterBlocker('dca', 'Enable trade mode management.', 'Trade mode management disabled'))
        if (!Number.isSafeInteger(config.accumulation_strategy_version_id) || Number(config.accumulation_strategy_version_id) <= 0) blockers.push(resolveControlCenterBlocker('accumulation_strategy_version_id', 'Select an exact compatible accumulation strategy version.', 'Accumulation strategy missing'))
        if (!['asap', 'csv_signal'].includes(String(config.signal))) blockers.push(resolveControlCenterBlocker('signal', 'Use ASAP fixed symbols or CSV inventory for accumulation.', 'Unsupported accumulation signal'))
        if (config.signal === 'asap' && /^https?:\/\//i.test(String(config.symbol_list ?? ''))) blockers.push(resolveControlCenterBlocker('symbol_list', 'Use fixed symbols for accumulation.', 'Fixed symbols required'))
        if (config.market !== 'spot') blockers.push(resolveControlCenterBlocker('market', 'Accumulation requires spot markets.', 'Spot market required'))
        if (config.autopilot === true) blockers.push(resolveControlCenterBlocker('autopilot', 'Disable Autopilot for accumulation.', 'Autopilot must be disabled'))
        return blockers
    }
    if (!Boolean(config.dca)) {
        return []
        }

        const requiredKeys: Array<[string, string, string]> = [
             [
                 'mstc',
                 'Max safety count missing',
                 'Set max safety order count for dynamic DCA.',
              ],
             [
                 'sos',
                 'Safety deviation missing',
                 'Set the first safety order deviation for dynamic DCA.',
              ],
          ]

    const blockers = requiredKeys.flatMap(([key, title, description]) =>
        hasRequiredValue(config[key])
            ? []
            : [resolveControlCenterBlocker(key, description, title)],
    )

    const recoveryTargetEnabled =
        isDynamicTradeMode(getTradeMode(config)) &&
        String(config.dynamic_so_sizing_mode ?? '')
            .trim()
            .toLowerCase() === 'recovery_target'
    if (recoveryTargetEnabled && !hasPositiveNumber(config.ss)) {
        blockers.push(
            resolveControlCenterBlocker(
                'ss',
                'Set a positive step scale so recovery safety-order spacing can advance.',
                'Recovery spacing scale missing',
            ),
        )
    }
    if (
        recoveryTargetEnabled &&
        !hasPositiveNumber(config.dynamic_so_max_deal_quote)
    ) {
        blockers.push(
            resolveControlCenterBlocker(
                'dynamic_so_max_deal_quote',
                'Set a positive quote-currency cap before recovery-target DCA can place safety orders.',
                'Recovery deal cap missing',
            ),
        )
    }

    return blockers
}

function countConfiguredEssentials(config: SharedConfigPayload): number {
    const keys = [
        'timezone',
        'exchange',
        'signal',
        'timeframe',
        'key',
        'secret',
        'currency',
    ]
    return keys.reduce(
        (count, key) => count + (hasRequiredValue(config[key]) ? 1 : 0),
        0,
    )
}

function deriveNextMode(
    blockers: ControlCenterBlocker[],
): ControlCenterMode {
    if (blockers.length > 0) {
        return blockers[0].mode
    }
    return 'setup'
}

export function deriveControlCenterReadiness(
    config: SharedConfigPayload | null,
): ControlCenterReadiness {
    if (!config) {
        return {
            complete: false,
            firstRun: true,
            attentionNeeded: false,
            blockers: [],
            nextMode: 'setup',
            nextTarget: 'exchange',
            dryRun: true,
            configuredEssentials: 0,
        }
    }

    const blockers = [
        ...collectAlwaysRequiredBlockers(config),
        ...collectDcaBlockers(config),
        ...deriveSignalModeBlockers(config),
    ]
    const complete = blockers.length === 0
    const configuredEssentials = countConfiguredEssentials(config)
    const firstRun = !complete && configuredEssentials <= 2
    const attentionNeeded = !complete && !firstRun
    const dryRun = Boolean(config.dry_run ?? true)
    const nextTarget = complete
        ? dryRun
            ? 'live-activation'
            : null
        : blockers[0]?.target ?? 'exchange'

    return {
        complete,
        firstRun,
        attentionNeeded,
        blockers,
        nextMode: deriveNextMode(blockers),
        nextTarget,
        dryRun,
        configuredEssentials,
    }
}
