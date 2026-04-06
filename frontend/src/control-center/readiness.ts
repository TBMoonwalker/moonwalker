import { resolveControlCenterBlocker } from './blockers'
import { deriveSignalModeBlockers } from './signalMode'
import { getTaskPresentation } from './taskRegistry'
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
            'history_lookback_time',
            'History window missing',
            'Set the history lookback window so indicators can initialize reliably.',
        ],
    ]

    return requiredKeys.flatMap(([key, title, description]) =>
        hasRequiredValue(config[key])
            ? []
            : [resolveControlCenterBlocker(key, description, title)],
    )
}

function collectDcaBlockers(config: SharedConfigPayload): ControlCenterBlocker[] {
    if (!Boolean(config.dca)) {
        return []
    }

    const requiredKeys: Array<[string, string, string]> = Boolean(config.dynamic_dca)
        ? [
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
        : [
              [
                  'so',
                  'Safety order amount missing',
                  'Set the safety order amount before using classic DCA.',
              ],
              [
                  'mstc',
                  'Max safety count missing',
                  'Set max safety order count before using classic DCA.',
              ],
              [
                  'sos',
                  'Safety deviation missing',
                  'Set the first safety order deviation before using classic DCA.',
              ],
              [
                  'ss',
                  'Step scale missing',
                  'Set the safety order step scale before using classic DCA.',
              ],
              [
                  'os',
                  'Volume scale missing',
                  'Set the safety order volume scale before using classic DCA.',
              ],
          ]

    return requiredKeys.flatMap(([key, title, description]) =>
        hasRequiredValue(config[key])
            ? []
            : [resolveControlCenterBlocker(key, description, title)],
    )
}

function countConfiguredEssentials(config: SharedConfigPayload): number {
    const keys = ['timezone', 'exchange', 'signal', 'timeframe', 'key', 'secret', 'currency']
    return keys.reduce(
        (count, key) => count + (hasRequiredValue(config[key]) ? 1 : 0),
        0,
    )
}

function deriveNextMode(
    blockers: ControlCenterBlocker[],
    complete: boolean,
    dryRun: boolean,
): ControlCenterMode {
    if (blockers.length > 0) {
        return blockers[0].mode
    }
    if (complete && dryRun) {
        return 'overview'
    }
    return complete ? 'overview' : 'setup'
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
        nextMode: deriveNextMode(blockers, complete, dryRun),
        nextTarget,
        dryRun,
        configuredEssentials,
    }
}
