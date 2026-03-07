type UiTelemetryValue = string | number | boolean | null
type UiTelemetryPayload = Record<string, UiTelemetryValue>

interface UiTelemetryEvent {
  name: string
  at: string
  payload?: UiTelemetryPayload
}

interface UiTelemetryStore {
  events: UiTelemetryEvent[]
}

declare global {
  interface Window {
    __moonwalkerUiTelemetry?: UiTelemetryStore
  }
}

const MAX_EVENTS = 250
let telemetryInitialized = false

function getStore(): UiTelemetryStore {
  if (!window.__moonwalkerUiTelemetry) {
    window.__moonwalkerUiTelemetry = { events: [] }
  }
  return window.__moonwalkerUiTelemetry
}

function pushEvent(event: UiTelemetryEvent): void {
  const store = getStore()
  store.events.push(event)
  if (store.events.length > MAX_EVENTS) {
    store.events.shift()
  }
}

export function trackUiEvent(name: string, payload?: UiTelemetryPayload): void {
  const event: UiTelemetryEvent = {
    name,
    at: new Date().toISOString(),
    payload,
  }
  pushEvent(event)
  console.debug(`[ui] ${name}`, payload ?? {})
}

function isSupportedEntryType(type: string): boolean {
  return (
    'PerformanceObserver' in window &&
    Array.isArray(PerformanceObserver.supportedEntryTypes) &&
    PerformanceObserver.supportedEntryTypes.includes(type)
  )
}

function observeLcp(): void {
  if (!isSupportedEntryType('largest-contentful-paint')) {
    return
  }
  const observer = new PerformanceObserver((entryList) => {
    const entries = entryList.getEntries()
    const latest = entries[entries.length - 1]
    if (!latest) {
      return
    }
    trackUiEvent('perf_lcp', {
      value_ms: Math.round(latest.startTime),
    })
  })
  observer.observe({ type: 'largest-contentful-paint', buffered: true })
}

function observeInp(): void {
  if (!isSupportedEntryType('event')) {
    return
  }

  let highestInp = 0
  const observer = new PerformanceObserver((entryList) => {
    for (const entry of entryList.getEntries()) {
      const eventEntry = entry as PerformanceEntry & {
        interactionId?: number
      }
      if (!eventEntry.interactionId || eventEntry.interactionId <= 0) {
        continue
      }
      if (entry.duration > highestInp) {
        highestInp = entry.duration
        trackUiEvent('perf_inp', {
          value_ms: Math.round(highestInp),
        })
      }
    }
  })
  observer.observe({ type: 'event', buffered: true, durationThreshold: 40 })
}

export function initUiTelemetry(): void {
  if (telemetryInitialized) {
    return
  }
  telemetryInitialized = true
  trackUiEvent('telemetry_initialized')
  observeLcp()
  observeInp()
}
