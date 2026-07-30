export type ReplayCandleRow = Record<string, number>

const MINIMUM_REPLAY_COVERAGE_RATIO = 0.8

function candleTimesMs(rows: ReplayCandleRow[]): number[] {
    return rows
        .map((row) => Number(row.time) * 1000)
        .filter((time) => Number.isFinite(time))
        .sort((left, right) => left - right)
}

export function replayNeedsHistoryFallback(
    rows: ReplayCandleRow[],
    historyStartMs: number,
    historyEndMs: number | null,
    timeframeSeconds: number,
): boolean {
    const times = candleTimesMs(rows)
    if (times.length === 0) {
        return true
    }
    if (historyEndMs === null) {
        return false
    }

    const timeframeMs = timeframeSeconds * 1000
    if (
        !Number.isFinite(historyStartMs) ||
        !Number.isFinite(historyEndMs) ||
        !Number.isFinite(timeframeMs) ||
        timeframeMs <= 0 ||
        historyEndMs <= historyStartMs
    ) {
        return false
    }

    const expectedCount =
        Math.floor((historyEndMs - historyStartMs) / timeframeMs) + 1
    const minimumCount = Math.max(
        2,
        Math.ceil(expectedCount * MINIMUM_REPLAY_COVERAGE_RATIO),
    )
    const firstTime = times[0]
    const lastTime = times[times.length - 1]

    return (
        times.length < minimumCount ||
        firstTime > historyStartMs + timeframeMs ||
        lastTime < historyEndMs - timeframeMs
    )
}

export function mergeReplayCandleRows(
    archiveRows: ReplayCandleRow[],
    historyRows: ReplayCandleRow[],
): ReplayCandleRow[] {
    const rowsByTime = new Map<number, ReplayCandleRow>()
    for (const row of [...historyRows, ...archiveRows]) {
        const time = Number(row.time)
        if (Number.isFinite(time)) {
            rowsByTime.set(time, row)
        }
    }

    return [...rowsByTime.entries()]
        .sort(([left], [right]) => left - right)
        .map(([, row]) => row)
}
