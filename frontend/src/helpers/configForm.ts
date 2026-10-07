const URL_PATTERN = /^https?:\/\//i
const WEBSOCKET_URL_PATTERN = /^wss?:\/\//i

const VOLUME_MULTIPLIERS: Record<string, number> = {
    K: 1_000,
    M: 1_000_000,
    B: 1_000_000_000,
    T: 1_000_000_000_000,
}

type StructuredConfigValue = Record<string, unknown>
export type ConfigValueType = 'str' | 'bool' | 'int' | 'float'

export interface ConfigUpdatePayload {
    value: unknown
    type: ConfigValueType
}

export interface SignalSettingsInput {
    signal: string | null
    symsignal_url: string | null
    symsignal_key: string | null
    symsignal_version: string | null
    symsignal_allowedsignals: unknown[]
    csvsignal_mode: string | null
    csvsignal_source: string | null
    csvsignal_inline: string | null
    websocket_url?: string | null
    websocket_headers?: string | null
    websocket_subscribe_message?: string | null
    websocket_required_decision?: string | null
    websocket_min_confidence?: number | null
    websocket_accepted_exchanges?: string | null
    websocket_accepted_market_states?: string | null
}

export function serializeConfigValue(
    value: unknown,
    type: ConfigValueType,
): ConfigUpdatePayload {
    return { value, type }
}

export function toNullableConfigString(
    value: string | null | undefined,
): string | null {
    if (value === null || value === undefined) {
        return null
    }

    const normalized = value.trim()
    return normalized.length > 0 ? normalized : null
}

function parseOptionalJsonConfigValue(value: string | null): unknown {
    const normalized = toNullableConfigString(value)
    if (normalized === null) {
        return null
    }

    const parsed = JSON.parse(normalized)
    if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
        throw new TypeError('Expected JSON object')
    }
    return parsed
}

function parseOptionalJsonOrStringConfigValue(value: string | null): unknown {
    const normalized = toNullableConfigString(value)
    if (normalized === null) {
        return null
    }

    try {
        return JSON.parse(normalized)
    } catch {
        return normalized
    }
}

export function getDefaultHistoryLookbackByTimeframe(
    timeframe: string | null,
): string {
    const normalized = String(timeframe || '').trim().toLowerCase()
    if (normalized === '1m') {
        return '30d'
    }
    if (normalized === '15m') {
        return '90d'
    }
    if (normalized === '1h') {
        return '180d'
    }
    if (normalized === '4h') {
        return '1y'
    }
    if (normalized === '1d') {
        return '3y'
    }
    if (normalized === '1w') {
        return '5y'
    }
    return '90d'
}

export function parseSymbolListToArray(raw: string | null): string[] {
    if (!raw) {
        return []
    }
    return raw
        .split(/[\n,]+/)
        .map((entry) => entry.trim().replace(/^['"]|['"]$/g, ''))
        .filter((entry) => entry.length > 0)
}

export function parseStructuredConfigValue(
    raw: unknown,
): StructuredConfigValue | null {
    if (!raw) {
        return null
    }

    if (typeof raw === 'object') {
        return raw as StructuredConfigValue
    }

    if (typeof raw !== 'string') {
        return null
    }

    try {
        return JSON.parse(raw) as StructuredConfigValue
    } catch (error) {
        console.error('Failed to parse structured config value:', error, raw)
        return null
    }
}

export function parseVolumeLimitToNumber(raw: unknown): number | null {
    const parsed = parseStructuredConfigValue(raw)
    if (!parsed) {
        return null
    }
    const range = String(parsed.range || '').toUpperCase()
    const size = Number(parsed.size)
    const multiplier = VOLUME_MULTIPLIERS[range]
    if (!Number.isFinite(size) || !multiplier) {
        return null
    }
    return size * multiplier
}

export function buildVolumeConfig(
    rawVolume: number | null,
): StructuredConfigValue | null {
    if (rawVolume === null || rawVolume === undefined) {
        return null
    }
    const value = Number(rawVolume)
    if (!Number.isFinite(value) || value <= 0) {
        return null
    }

    const ranges: Array<{ range: string; multiplier: number }> = [
        { range: 'T', multiplier: 1_000_000_000_000 },
        { range: 'B', multiplier: 1_000_000_000 },
        { range: 'M', multiplier: 1_000_000 },
        { range: 'K', multiplier: 1_000 },
    ]
    const selected =
        ranges.find((entry) => value >= entry.multiplier) || {
            range: 'K',
            multiplier: 1_000,
        }

    return {
        size: Number((value / selected.multiplier).toFixed(3)),
        range: selected.range,
    }
}

export function splitEntries(raw: string): string[] {
    return raw
        .split(/[\n,]+/)
        .map((entry) => entry.trim().replace(/^['"]|['"]$/g, ''))
        .filter((entry) => entry.length > 0)
}

export function toTokenOnlyEntries(raw: string | null): string | null {
    if (!raw) {
        return raw
    }

    const normalizedRaw = raw.trim()
    if (!normalizedRaw || URL_PATTERN.test(normalizedRaw)) {
        return raw
    }

    const entries = splitEntries(normalizedRaw)
    if (entries.length === 0) {
        return raw
    }

    const tokens = entries.map((entry) =>
        entry.toUpperCase().replace('-', '/').split('/')[0],
    )
    return tokens.join(',')
}

export function normalizePairEntries(
    raw: string | null,
    quoteCurrency: string,
) : string | null {
    if (!raw) {
        return null
    }

    const normalizedRaw = raw.trim()
    if (!normalizedRaw) {
        return null
    }

    if (URL_PATTERN.test(normalizedRaw)) {
        return normalizedRaw
    }

    const entries = splitEntries(normalizedRaw)
    if (entries.length === 0) {
        return null
    }

    const quote = quoteCurrency.toUpperCase()
    const pairs = entries.map((entry) => {
        const normalizedEntry = entry.toUpperCase().replace('-', '/')
        if (normalizedEntry.includes('/')) {
            const [base, q] = normalizedEntry.split('/')
            if (base && q) {
                return `${base}/${q}`
            }
            return `${base}/${quote}`
        }
        return `${normalizedEntry}/${quote}`
    })

    return pairs.join(',')
}

export function buildSignalSettingsValue(
    input: SignalSettingsInput,
): StructuredConfigValue | null {
    if (input.signal === 'sym_signals') {
        return {
            api_url: toNullableConfigString(input.symsignal_url),
            api_key: toNullableConfigString(input.symsignal_key),
            api_version: toNullableConfigString(input.symsignal_version),
            allowed_signals: input.symsignal_allowedsignals,
        }
    }
    if (input.signal === 'csv_signal') {
        const csvSourceValue =
            input.csvsignal_mode === 'inline'
                ? input.csvsignal_inline
                : input.csvsignal_source
        return {
            csv_source: toNullableConfigString(csvSourceValue),
        }
    }
    if (input.signal === 'websocket_signal') {
        const settings: StructuredConfigValue = {
            websocket_url: toNullableConfigString(input.websocket_url),
        }
        const headers = parseOptionalJsonConfigValue(input.websocket_headers)
        if (headers !== null) {
            settings.headers = headers
        }
        const subscribeMessage = parseOptionalJsonOrStringConfigValue(
            input.websocket_subscribe_message,
        )
        if (subscribeMessage !== null) {
            settings.subscribe_message = subscribeMessage
        }
        const requiredDecision = toNullableConfigString(
            input.websocket_required_decision,
        )
        if (requiredDecision !== null && requiredDecision !== 'take_trade') {
            settings.required_decision = requiredDecision
        }
        if (
            input.websocket_min_confidence !== null &&
            input.websocket_min_confidence !== undefined
        ) {
            settings.min_confidence = input.websocket_min_confidence
        }
        const acceptedExchanges = toNullableConfigString(
            input.websocket_accepted_exchanges,
        )
        if (acceptedExchanges !== null) {
            settings.accepted_exchanges = acceptedExchanges
        }
        const acceptedMarketStates = toNullableConfigString(
            input.websocket_accepted_market_states,
        )
        if (acceptedMarketStates !== null) {
            settings.accepted_market_states = acceptedMarketStates
        }
        return settings
    }
    return null
}

export function isWebsocketUrl(value: string | null): boolean {
    return value !== null && WEBSOCKET_URL_PATTERN.test(value.trim())
}
