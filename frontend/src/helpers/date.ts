const TRADINGVIEW_MONTH_FORMATTER = new Intl.DateTimeFormat('en-GB', {
  month: 'short',
})

const MONTH_TO_INDEX: Record<string, number> = {
  jan: 0,
  feb: 1,
  mar: 2,
  apr: 3,
  may: 4,
  jun: 5,
  jul: 6,
  aug: 7,
  sep: 8,
  oct: 9,
  nov: 10,
  dec: 11,
}

function parseNumericDate(value: string): Date | null {
  if (!/^-?\d+(?:\.\d+)?$/.test(value)) {
    return null
  }
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) {
    return null
  }
  const timestampMs = normalizeEpochToMs(numeric)
  const parsed = new Date(timestampMs)
  return Number.isNaN(parsed.getTime()) ? null : parsed
}

function normalizeEpochToMs(value: number): number {
  const absValue = Math.abs(value)
  if (absValue >= 1_000_000_000_000_000_000) {
    return value / 1_000_000
  }
  if (absValue >= 1_000_000_000_000_000) {
    return value / 1_000
  }
  if (absValue >= 1_000_000_000_000) {
    return value
  }
  return value * 1_000
}

function parseTradingViewLikeDate(value: string): Date | null {
  const match = value.match(
    /^(\d{2})\s+([A-Za-z]{3})\s+(\d{2})(?:\s+(\d{2}):(\d{2})(?::(\d{2}))?)?$/
  )
  if (!match) {
    return null
  }

  const day = Number(match[1])
  const monthIndex = MONTH_TO_INDEX[match[2].toLowerCase()]
  const year = 2000 + Number(match[3])
  const hours = Number(match[4] ?? '0')
  const minutes = Number(match[5] ?? '0')
  const seconds = Number(match[6] ?? '0')

  if (
    !Number.isFinite(day) ||
    monthIndex === undefined ||
    !Number.isFinite(year) ||
    !Number.isFinite(hours) ||
    !Number.isFinite(minutes) ||
    !Number.isFinite(seconds)
  ) {
    return null
  }

  const parsed = new Date(year, monthIndex, day, hours, minutes, seconds)
  return Number.isNaN(parsed.getTime()) ? null : parsed
}

function normalizeIsoCandidate(value: string): string {
  const withTSeparator =
    value.includes(' ') && !value.includes('T') ? value.replace(' ', 'T') : value
  const truncatedFraction = withTSeparator.replace(
    /(\.\d{3})\d+([zZ]|[+-]\d{2}:\d{2})?$/,
    '$1$2'
  )
  return truncatedFraction
}

export function parseDateValue(value: string | number | Date): Date | null {
  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? null : value
  }

  if (typeof value === 'number') {
    if (!Number.isFinite(value)) {
      return null
    }
    const timestampMs = normalizeEpochToMs(value)
    const parsed = new Date(timestampMs)
    return Number.isNaN(parsed.getTime()) ? null : parsed
  }

  const trimmed = value.trim()
  if (!trimmed) {
    return null
  }

  const numericDate = parseNumericDate(trimmed)
  if (numericDate) {
    return numericDate
  }

  const tradingViewLikeDate = parseTradingViewLikeDate(trimmed)
  if (tradingViewLikeDate) {
    return tradingViewLikeDate
  }

  const normalized = normalizeIsoCandidate(trimmed)
  const normalizedWithTimezone = /[zZ]|[+-]\d{2}:\d{2}$/.test(normalized)
    ? normalized
    : `${normalized}Z`

  const parsedNormalized = new Date(normalizedWithTimezone)
  if (!Number.isNaN(parsedNormalized.getTime())) {
    return parsedNormalized
  }

  const parsedRaw = new Date(trimmed)
  return Number.isNaN(parsedRaw.getTime()) ? null : parsedRaw
}

export function formatTradingViewDate(value: string | number | Date): string {
  const parsed = parseDateValue(value)
  if (!parsed) {
    return String(value)
  }
  const { date, time } = formatTradingViewDateParts(parsed)
  return `${date} ${time}`
}

export function formatTradingViewDateParts(
  value: string | number | Date
): { date: string; time: string } {
  const parsed = value instanceof Date ? value : parseDateValue(value)
  if (!parsed) {
    return { date: String(value), time: '' }
  }
  const day = String(parsed.getDate()).padStart(2, '0')
  const month = TRADINGVIEW_MONTH_FORMATTER.format(parsed)
  const year = String(parsed.getFullYear()).slice(-2)
  const hours = String(parsed.getHours()).padStart(2, '0')
  const minutes = String(parsed.getMinutes()).padStart(2, '0')
  return {
    date: `${day} ${month} ${year}`,
    time: `${hours}:${minutes}`,
  }
}
