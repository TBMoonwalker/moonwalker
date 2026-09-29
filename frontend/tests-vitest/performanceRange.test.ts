import { describe, expect, it } from 'vitest'
import { filterPerformancePoints, type PerformancePoint } from '../src/helpers/performanceRange'

const now = Date.parse('2026-09-28T12:00:00Z')
const point = (timestamp: string): PerformancePoint => ({
  timestamp,
  profit_overall: 10,
  funds_locked: 20,
})

describe('performance range', () => {
  const points = [
    point('2025-09-27 12:00:00'),
    point('2025-09-28 12:00:00'),
    point('2026-08-29 12:00:00'),
    point('2026-09-27 12:00:00'),
    point('2026-09-28 12:00:00'),
  ]

  it('maps the switcher to exact elapsed-day windows', () => {
    expect(filterPerformancePoints(points, 'all', now)).toHaveLength(5)
    expect(filterPerformancePoints(points, '1d', now)).toHaveLength(2)
    expect(filterPerformancePoints(points, '30d', now)).toHaveLength(3)
    expect(filterPerformancePoints(points, '365d', now)).toHaveLength(4)
  })

  it('keeps explicit UTC offsets and excludes invalid or future points', () => {
    const mixed = [
      point('2026-09-28T13:00:00+02:00'),
      point('invalid'),
      point('2026-09-29 12:00:00'),
    ]
    expect(filterPerformancePoints(mixed, '1d', now)).toEqual([mixed[0]])
  })
})
