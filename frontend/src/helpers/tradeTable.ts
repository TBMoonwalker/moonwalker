import { formatTradingViewDateParts } from './date'

const TIMEZONELESS_TRADE_DATETIME_PATTERN =
    /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,6}))?)?$/

export type TradeTableSortOrder = 'ascend' | 'descend'

export type TradeTableSortState = {
    columnKey: string
    order: TradeTableSortOrder
}

export type TradeTableSortValueKind = 'number' | 'date' | 'text'

export const OPEN_TRADES_MOBILE_COLUMN_KEYS = [
    'symbol',
    'cost',
    'display_profit_percent',
    'action',
] as const

export const OPEN_TRADES_TABLET_COLUMN_KEYS = [
    'symbol',
    'cost',
    'display_profit_percent',
    'action',
    'open_date',
] as const

export const CLOSED_TRADES_MOBILE_COLUMN_KEYS = [
    'symbol',
    'profit',
    'cost',
    'profit_percent',
    'close_date',
    'action',
] as const

export const CLOSED_TRADES_TABLET_COLUMN_KEYS = [
    'symbol',
    'amount',
    'profit',
    'cost',
    'profit_percent',
    'close_reason',
    'so_count',
    'close_date',
    'action',
] as const

export type TradeTableSortResolver<T> = {
    kind: TradeTableSortValueKind
    value: (row: T) => unknown
}

export function shouldShowTradeTableColumn(
    columnKey: unknown,
    visibleKeys: readonly string[],
): boolean {
    return visibleKeys.includes(String(columnKey))
}

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

function normalizeTradeTableSortOrder(rawValue: unknown): TradeTableSortOrder | null {
    return rawValue === 'ascend' || rawValue === 'descend' ? rawValue : null
}

function normalizeTradeTableSortKey(rawValue: unknown): string | null {
    if (typeof rawValue !== 'string' && typeof rawValue !== 'number') {
        return null
    }
    const normalized = String(rawValue).trim()
    return normalized ? normalized : null
}

export function resolveTradeTableSortState(
    sorter: unknown,
): TradeTableSortState | null {
    const candidate = Array.isArray(sorter) ? sorter[0] : sorter
    if (!candidate || typeof candidate !== 'object') {
        return null
    }

    const sortCandidate = candidate as {
        columnKey?: unknown
        order?: unknown
    }
    const columnKey = normalizeTradeTableSortKey(sortCandidate.columnKey)
    const order = normalizeTradeTableSortOrder(sortCandidate.order)
    if (!columnKey || !order) {
        return null
    }
    return { columnKey, order }
}

export function resolveTradeTableColumnOrder(
    sortState: TradeTableSortState | null,
    columnKey: string,
): TradeTableSortOrder | false {
    if (!sortState || sortState.columnKey !== columnKey) {
        return false
    }
    return sortState.order
}

export function resolveTradeSortTimestamp(value: unknown): number | null {
    if (value instanceof Date) {
        const time = value.getTime()
        return Number.isNaN(time) ? null : time
    }
    const normalized = String(value ?? '').trim()
    if (!normalized) {
        return null
    }

    const timezoneLessTradeDate = parseTimezoneLessTradeDate(normalized)
    if (timezoneLessTradeDate) {
        return timezoneLessTradeDate.getTime()
    }

    const parsed = Date.parse(normalized)
    return Number.isFinite(parsed) ? parsed : null
}

function normalizeTradeTableSortValue(
    value: unknown,
    kind: TradeTableSortValueKind,
): number | string | null {
    if (kind === 'number') {
        const parsed = Number(value)
        return Number.isFinite(parsed) ? parsed : null
    }
    if (kind === 'date') {
        return resolveTradeSortTimestamp(value)
    }
    const normalized = String(value ?? '').trim()
    return normalized ? normalized.toLowerCase() : null
}

export function sortTradeRows<T>(
    rows: T[],
    sortState: TradeTableSortState | null,
    resolvers: Record<string, TradeTableSortResolver<T>>,
): T[] {
    if (!sortState) {
        return rows
    }

    const resolver = resolvers[sortState.columnKey]
    if (!resolver) {
        return rows
    }

    const direction = sortState.order === 'ascend' ? 1 : -1
    return [...rows].sort((leftRow, rightRow) => {
        const leftValue = normalizeTradeTableSortValue(
            resolver.value(leftRow),
            resolver.kind,
        )
        const rightValue = normalizeTradeTableSortValue(
            resolver.value(rightRow),
            resolver.kind,
        )

        if (leftValue === null && rightValue === null) {
            return 0
        }
        if (leftValue === null) {
            return 1
        }
        if (rightValue === null) {
            return -1
        }
        if (typeof leftValue === 'number' && typeof rightValue === 'number') {
            return (leftValue - rightValue) * direction
        }
        return leftValue.localeCompare(rightValue) * direction
    })
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
