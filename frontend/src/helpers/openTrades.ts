export type TimeframeChoice = {
    timerange: string
    seconds: number
}

export type OpenTradesConfigResponse = {
    timeframe?: string | null
}

export type OrderData = {
    id: number
    timestamp: string
    ordersize: number
    amount: number
    symbol: string
    price: number
    so_percentage?: number
}

export type OpenTradeRow = {
    id: number
    symbol: string
    amount: number
    cost: number
    profit: number
    profit_percent: number
    current_price: number
    tp_price: number
    avg_price: number
    so_count: number
    open_date: string
    baseorder: OrderData
    safetyorder: OrderData[]
    precision: number
    unsellable_amount?: number
    unsellable_reason?: string | null
    unsellable_min_notional?: number | null
    unsellable_estimated_notional?: number | null
}

export const TIMEFRAME_CHOICES: TimeframeChoice[] = [
    { timerange: '1m', seconds: 60 },
    { timerange: '5min', seconds: 5 * 60 },
    { timerange: '15min', seconds: 15 * 60 },
    { timerange: '30min', seconds: 30 * 60 },
    { timerange: '60min', seconds: 60 * 60 },
    { timerange: '4h', seconds: 4 * 60 * 60 },
    { timerange: '1D', seconds: 24 * 60 * 60 },
]

export const DEFAULT_MIN_TIMEFRAME = TIMEFRAME_CHOICES[2]

export function parseTimeframeSeconds(
    rawValue: string | null | undefined,
): number | null {
    const normalized = String(rawValue ?? '').trim().toLowerCase().replace(
        'min',
        'm',
    )
    const match = normalized.match(/^(\d+)([mhd])$/)
    if (!match) {
        return null
    }
    const value = Number(match[1])
    const unit = match[2]
    if (!Number.isFinite(value) || value <= 0) {
        return null
    }
    if (unit === 'm') {
        return value * 60
    }
    if (unit === 'h') {
        return value * 60 * 60
    }
    if (unit === 'd') {
        return value * 24 * 60 * 60
    }
    return null
}

export function resolveMinTimeframe(
    configured: string | null | undefined,
    fallback: TimeframeChoice = DEFAULT_MIN_TIMEFRAME,
): TimeframeChoice {
    const configuredSeconds = parseTimeframeSeconds(configured)
    if (!configuredSeconds) {
        return fallback
    }
    const matching = TIMEFRAME_CHOICES.find(
        (choice) => choice.seconds >= configuredSeconds,
    )
    return matching ?? TIMEFRAME_CHOICES[TIMEFRAME_CHOICES.length - 1]
}

export function splitTradeSymbol(value: string): [string, string] {
    const [symbol = '', currency = ''] = String(value).split('/')
    return [symbol, currency]
}

export function getSafetyOrderCount(rowData: OpenTradeRow): number {
    if (Array.isArray(rowData.safetyorder)) {
        return rowData.safetyorder.length
    }
    return Number(rowData.so_count ?? 0)
}

export function isUnsellableRemainder(rowData: OpenTradeRow): boolean {
    return (
        Number(rowData.unsellable_amount ?? 0) > 0 &&
        Boolean(rowData.unsellable_reason)
    )
}

export function getUnsellableMessage(rowData: OpenTradeRow): string {
    const remainingAmount = Number(rowData.unsellable_amount ?? 0)
    const [symbol] = splitTradeSymbol(rowData.symbol)
    const estimatedNotional = rowData.unsellable_estimated_notional
    const minNotional = rowData.unsellable_min_notional

    const parts: string[] = [
        `Unsellable remainder for ${rowData.symbol}: ${remainingAmount.toFixed(8)} ${symbol}.`,
    ]
    if (estimatedNotional !== null && estimatedNotional !== undefined) {
        parts.push(
            `Estimated notional: ${Number(estimatedNotional).toFixed(8)}.`,
        )
    }
    if (minNotional !== null && minNotional !== undefined) {
        parts.push(
            `Minimum notional required: ${Number(minNotional).toFixed(8)}.`,
        )
    }
    parts.push('Use Stop and close the remainder manually on the exchange.')
    return parts.join(' ')
}

export function toFiniteNonNegative(value: unknown): number {
    const parsed = Number(value)
    if (!Number.isFinite(parsed) || parsed < 0) {
        return 0
    }
    return parsed
}

export function formatOrderAmount(value: number): string {
    const normalized = toFiniteNonNegative(value)
    return normalized.toFixed(2)
}

export function formatPrice(value: number): string {
    return toFiniteNonNegative(value).toFixed(8).replace(/\.?0+$/, '')
}

export function clampToRange(value: number, min: number, max: number): number {
    if (!Number.isFinite(value)) {
        return min
    }
    return Math.max(min, Math.min(max, value))
}

export function floorToDecimals(value: number, decimals: number): number {
    const factor = 10 ** decimals
    return Math.floor(value * factor) / factor
}

export function roundToDecimals(value: number, decimals: number): number {
    const factor = 10 ** decimals
    return Math.round(value * factor) / factor
}

export function snapToMarkers(
    value: number,
    markers: number[],
    tolerance: number,
): number {
    for (const marker of markers) {
        if (Math.abs(value - marker) <= tolerance) {
            return marker
        }
    }
    return value
}

export function getPreviousBuyPrice(rowData: OpenTradeRow): number {
    if (Array.isArray(rowData.safetyorder) && rowData.safetyorder.length > 0) {
        const sortedSafetyOrders = [...rowData.safetyorder].sort(
            (a, b) => Number(a.timestamp) - Number(b.timestamp),
        )
        const lastSafetyOrder = sortedSafetyOrders[sortedSafetyOrders.length - 1]
        return Number(lastSafetyOrder.price) || 0
    }
    return Number(rowData.baseorder?.price) || Number(rowData.avg_price) || 0
}

export function calculateSoPercentage(
    price: number,
    previousPrice: number,
): number {
    if (
        !Number.isFinite(price) ||
        !Number.isFinite(previousPrice) ||
        previousPrice <= 0
    ) {
        return 0
    }
    return Number((((price - previousPrice) / previousPrice) * 100).toFixed(2))
}
