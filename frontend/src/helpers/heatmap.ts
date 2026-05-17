export interface HeatmapPoint {
    timestamp: number
    value: number
}

export function normalizeTradeHeatmapData(data: HeatmapPoint[]): HeatmapPoint[] {
    const dayBuckets = new Map<number, number>()
    for (const item of data) {
        if (!Number.isFinite(item.timestamp)) {
            continue
        }

        const timestamp = utcDayStart(item.timestamp)
        dayBuckets.set(
            timestamp,
            (dayBuckets.get(timestamp) ?? 0) + Math.max(0, item.value),
        )
    }

    const sorted = [...dayBuckets.entries()].sort((a, b) => a[0] - b[0])
    if (!sorted.length) {
        return []
    }

    const first = new Date(sorted[0][0])
    const last = new Date(sorted[sorted.length - 1][0])
    const calendarStart = Date.UTC(first.getUTCFullYear(), first.getUTCMonth(), 1)
    const calendarEnd = Date.UTC(
        last.getUTCFullYear(),
        last.getUTCMonth() + 1,
        0,
    )

    dayBuckets.set(calendarStart, dayBuckets.get(calendarStart) ?? 0)
    dayBuckets.set(calendarEnd, dayBuckets.get(calendarEnd) ?? 0)

    return [...dayBuckets.entries()]
        .sort((a, b) => a[0] - b[0])
        .map(([timestamp, value]) => ({ timestamp, value }))
}

function utcDayStart(timestamp: number): number {
    const date = new Date(timestamp)
    return Date.UTC(
        date.getUTCFullYear(),
        date.getUTCMonth(),
        date.getUTCDate(),
    )
}
