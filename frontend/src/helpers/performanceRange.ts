export type PerformanceRange = 'all' | '1d' | '30d' | '365d'

export interface PerformancePoint {
  timestamp: string
  profit_overall: number
  funds_locked: number
}

const RANGE_DAYS: Record<Exclude<PerformanceRange, 'all'>, number> = {
  '1d': 1,
  '30d': 30,
  '365d': 365,
}

function timestampMilliseconds(timestamp: string): number {
  // The timeline endpoint emits naive UTC timestamps such as 2026-09-28 10:15:00.
  const normalized = timestamp.includes('T') ? timestamp : timestamp.replace(' ', 'T')
  const zoned = /(?:Z|[+-]\d{2}:\d{2})$/i.test(normalized)
    ? normalized
    : `${normalized}Z`
  return Date.parse(zoned)
}

export function filterPerformancePoints(
  points: PerformancePoint[],
  range: PerformanceRange,
  now = Date.now(),
): PerformancePoint[] {
  if (range === 'all') return points

  const cutoff = now - RANGE_DAYS[range] * 24 * 60 * 60 * 1000
  return points.filter((point) => {
    const timestamp = timestampMilliseconds(point.timestamp)
    return Number.isFinite(timestamp) && timestamp >= cutoff && timestamp <= now
  })
}
