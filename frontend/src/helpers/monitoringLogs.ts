export type MonitoringLogLevel =
  | 'all'
  | 'trace+'
  | 'debug+'
  | 'info+'
  | 'warning+'
  | 'error+'
  | 'critical'

const LEVEL_ORDER: Record<string, number> = {
  TRACE: 10,
  DEBUG: 20,
  INFO: 30,
  WARNING: 40,
  ERROR: 50,
  CRITICAL: 60,
}

export function parseMonitoringLogLevel(line: string): string | null {
  const matched = line.match(/ - (TRACE|DEBUG|INFO|WARNING|ERROR|CRITICAL) - /)
  return matched?.[1] ?? null
}

export function filterMonitoringLogLines(
  lines: string[],
  minimumLevel: MonitoringLogLevel,
): string[] {
  if (minimumLevel === 'all') {
    return lines
  }

  if (minimumLevel === 'critical') {
    return lines.filter((line) => parseMonitoringLogLevel(line) === 'CRITICAL')
  }

  const requiredOrder = LEVEL_ORDER[minimumLevel.replace('+', '').toUpperCase()]
  return lines.filter((line) => {
    const parsedLevel = parseMonitoringLogLevel(line)
    if (parsedLevel === null) {
      return false
    }
    return LEVEL_ORDER[parsedLevel] >= requiredOrder
  })
}

export function appendMonitoringLogLines(
  existingLines: string[],
  incomingLines: string[],
  maxLines: number,
): string[] {
  if (incomingLines.length === 0) {
    return existingLines
  }

  const combined = existingLines.concat(incomingLines)
  if (combined.length <= maxLines) {
    return combined
  }
  return combined.slice(combined.length - maxLines)
}

export function prependMonitoringLogLines(
  existingLines: string[],
  olderLines: string[],
  maxLines: number,
): string[] {
  if (olderLines.length === 0) {
    return existingLines
  }

  const combined = olderLines.concat(existingLines)
  if (combined.length <= maxLines) {
    return combined
  }
  return combined.slice(0, maxLines)
}
