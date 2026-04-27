import { formatTradingViewDateParts } from './date'

const TIMEZONELESS_TRADE_DATETIME_PATTERN =
    /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,6}))?)?$/

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

function parseTimezoneLessTradeDate(value: string): Date | null {
    const match = value.trim().match(TIMEZONELESS_TRADE_DATETIME_PATTERN)
    if (!match) {
        return null
    }

    const [
        ,
        year,
        month,
        day,
        hours,
        minutes,
        seconds = '0',
        fraction = '0',
    ] = match
    const milliseconds = Number(fraction.slice(0, 3).padEnd(3, '0'))
    const parsed = new Date(
        Number(year),
        Number(month) - 1,
        Number(day),
        Number(hours),
        Number(minutes),
        Number(seconds),
        milliseconds,
    )
    return Number.isNaN(parsed.getTime()) ? null : parsed
}

export function resolveTradeDateTime(value: string): { date: string; time: string } {
    const localTradeDate = parseTimezoneLessTradeDate(value)
    if (localTradeDate) {
        return formatTradingViewDateParts(localTradeDate)
    }

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
