import { formatTradingViewDateParts } from './date'

export function formatFixed(value: unknown, decimals = 2): string {
    const parsed = Number(value)
    if (!Number.isFinite(parsed)) {
        return (0).toFixed(decimals)
    }
    return parsed.toFixed(decimals)
}

export function formatAssetAmount(value: unknown, maxDecimals = 8): string {
    const parsed = Number(value)
    if (!Number.isFinite(parsed)) {
        return '0'
    }
    return parsed.toFixed(maxDecimals).replace(/\.?0+$/, '')
}

export function resolveTradeDateTime(value: string): { date: string; time: string } {
    const parts = formatTradingViewDateParts(value)
    if (parts.time) {
        return parts
    }
    const raw = String(value).trim()
    const match = raw.match(/^(.*)\s(\d{2}:\d{2}(?::\d{2})?)$/)
    if (!match) {
        return parts
    }
    return { date: match[1], time: match[2] }
}
