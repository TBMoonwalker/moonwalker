const URL_PATTERN = /^https?:\/\//i

const VOLUME_MULTIPLIERS: Record<string, number> = {
    K: 1_000,
    M: 1_000_000,
    B: 1_000_000_000,
    T: 1_000_000_000_000,
}

type StructuredConfigValue = Record<string, unknown>

export interface SignalSettingsInput {
    signal: string | null
    symsignal_url: string | null
    symsignal_key: string | null
    symsignal_version: string | null
    symsignal_allowedsignals: unknown[]
    csvsignal_mode: string | null
    csvsignal_source: string | null
    csvsignal_inline: string | null
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

    const normalized = raw
        .replace(/'/g, '"')
        .replace(/\bTrue\b/g, 'true')
        .replace(/\bFalse\b/g, 'false')
        .replace(/\bNone\b/g, 'null')

    try {
        return JSON.parse(normalized) as StructuredConfigValue
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
): StructuredConfigValue | false {
    if (rawVolume === null || rawVolume === undefined) {
        return false
    }
    const value = Number(rawVolume)
    if (!Number.isFinite(value) || value <= 0) {
        return false
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
): string | false {
    if (!raw) {
        return false
    }

    const normalizedRaw = raw.trim()
    if (!normalizedRaw) {
        return false
    }

    if (URL_PATTERN.test(normalizedRaw)) {
        return normalizedRaw
    }

    const entries = splitEntries(normalizedRaw)
    if (entries.length === 0) {
        return false
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
): StructuredConfigValue | false {
    if (input.signal === 'sym_signals') {
        return {
            api_url: input.symsignal_url || false,
            api_key: input.symsignal_key || false,
            api_version: input.symsignal_version || false,
            allowed_signals: input.symsignal_allowedsignals,
        }
    }
    if (input.signal === 'csv_signal') {
        const csvSourceValue =
            input.csvsignal_mode === 'inline'
                ? input.csvsignal_inline
                : input.csvsignal_source
        return {
            csv_source: csvSourceValue || false,
        }
    }
    return false
}
