import { getTaskPresentation } from './taskRegistry'
import type { ControlCenterBlocker, SharedConfigPayload } from './types'

function toNullableString(value: unknown): string | null {
    if (value === null || value === undefined) {
        return null
    }
    const normalized = String(value).trim()
    return normalized.length > 0 && normalized.toLowerCase() !== 'false'
        ? normalized
        : null
}

function hasRequiredValue(value: unknown): boolean {
    return toNullableString(value) !== null
}

function parseSignalSettings(rawValue: unknown): Record<string, unknown> {
    if (rawValue && typeof rawValue === 'object') {
        return rawValue as Record<string, unknown>
    }
    if (typeof rawValue === 'string') {
        try {
            return JSON.parse(rawValue.replace(/'/g, '"')) as Record<string, unknown>
        } catch {
            return {}
        }
    }
    return {}
}

function buildSignalBlocker(
    key: string,
    title: string,
    description: string,
): ControlCenterBlocker {
    const task = getTaskPresentation('signal')
    return {
        key,
        title,
        description,
        mode: task.defaultMode,
        target: task.target,
    }
}

export function deriveSignalModeBlockers(
    config: SharedConfigPayload,
): ControlCenterBlocker[] {
    const signalName = toNullableString(config.signal)?.toLowerCase() ?? null
    const signalSettings = parseSignalSettings(config.signal_settings)

    if (signalName === 'asap' && !hasRequiredValue(config.symbol_list)) {
        return [
            buildSignalBlocker(
                'symbol_list',
                'ASAP symbols missing',
                'Add ASAP symbols directly or provide a URL to a symbol list.',
            ),
        ]
    }

    if (signalName === 'sym_signals') {
        const blockers: ControlCenterBlocker[] = []
        if (!hasRequiredValue(signalSettings.api_url)) {
            blockers.push(
                buildSignalBlocker(
                    'signal_settings.api_url',
                    'SymSignals URL missing',
                    'Add the SymSignals API URL before activating the signal source.',
                ),
            )
        }
        if (!hasRequiredValue(signalSettings.api_key)) {
            blockers.push(
                buildSignalBlocker(
                    'signal_settings.api_key',
                    'SymSignals key missing',
                    'Add the SymSignals API key before activating the signal source.',
                ),
            )
        }
        if (!hasRequiredValue(signalSettings.api_version)) {
            blockers.push(
                buildSignalBlocker(
                    'signal_settings.api_version',
                    'SymSignals version missing',
                    'Choose the SymSignals API version so the runtime can connect safely.',
                ),
            )
        }
        return blockers
    }

    if (signalName === 'csv_signal' && !hasRequiredValue(signalSettings.csv_source)) {
        return [
            buildSignalBlocker(
                'signal_settings.csv_source',
                'CSV source missing',
                'Add a CSV path, URL, or inline payload before using CSV signals.',
            ),
        ]
    }

    return []
}
