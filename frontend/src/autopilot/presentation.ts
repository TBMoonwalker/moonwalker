import type {
    AutopilotMemoryEvent,
    AutopilotMemoryPayload,
    AutopilotMemorySnapshot,
} from './types'

export function formatAutopilotReason(
    reasonCode: string | null | undefined,
    reasonValue: number | null | undefined,
): string {
    const value = Number.isFinite(Number(reasonValue)) ? Number(reasonValue) : null
    switch (reasonCode) {
        case 'quick_profitable_closes':
            return value
                ? `after ${value} quick profitable closes`
                : 'after quick profitable closes'
        case 'strong_profit_quality':
            return value
                ? `after ${value} clean profitable closes`
                : 'after strong recent profit quality'
        case 'slow_exits':
            return value
                ? `after ${value} slower exits`
                : 'after slower exits'
        case 'recent_losses':
            return value ? `after ${value} recent losses` : 'after recent losses'
        case 'thin_history':
            return value
                ? `still learning from ${value} closes`
                : 'still learning from recent closes'
        case 'refresh_failed':
            return 'memory refresh is behind'
        case 'snapshot_expired':
            return 'memory snapshot is stale'
        default:
            return 'based on recent close history'
    }
}

export function formatAutopilotEvent(event: AutopilotMemoryEvent): string {
    if (event.event_type === 'favored_symbol' && event.symbol) {
        return `Favored ${event.symbol} ${formatAutopilotReason(
            event.reason_code,
            event.reason_value,
        )}.`
    }
    if (event.event_type === 'cooling_symbol' && event.symbol) {
        return `Cooling ${event.symbol} ${formatAutopilotReason(
            event.reason_code,
            event.reason_value,
        )}.`
    }
    if (event.event_type === 'memory_stale') {
        return 'Baseline mode active while memory refreshes.'
    }
    if (event.event_type === 'memory_ready') {
        return 'Autopilot memory is ready to assist.'
    }
    if (event.event_type === 'memory_warming_up') {
        return event.reason_value
            ? `Learning from ${event.reason_value} closes so far.`
            : 'Learning from recent closes so far.'
    }
    return 'Autopilot memory updated.'
}

export function formatAutopilotFeaturedInsight(
    snapshot: AutopilotMemorySnapshot | null | undefined,
): string {
    if (!snapshot) {
        return 'No symbol memory yet.'
    }
    if (snapshot.trust_direction === 'cooling') {
        return `Cooling ${snapshot.symbol} ${formatAutopilotReason(
            snapshot.primary_reason_code,
            snapshot.primary_reason_value,
        )}.`
    }
    if (snapshot.trust_direction === 'favored') {
        return `Favored ${snapshot.symbol} ${formatAutopilotReason(
            snapshot.primary_reason_code,
            snapshot.primary_reason_value,
        )}.`
    }
    return `${snapshot.symbol} is still near neutral trust.`
}

export function formatAutopilotStatusTitle(
    payload: AutopilotMemoryPayload | null,
): string {
    if (!payload) {
        return 'Loading Autopilot memory'
    }
    if (payload.stale) {
        return 'Autopilot memory is stale'
    }
    if (payload.status === 'warming_up') {
        return 'Autopilot is still learning'
    }
    if (payload.status === 'fresh' && !payload.enabled) {
        return 'Autopilot memory is ready'
    }
    if (payload.status === 'fresh') {
        return 'Autopilot is making trust-based calls'
    }
    return 'Autopilot memory has no close history yet'
}

export function formatAutopilotStatusBody(
    payload: AutopilotMemoryPayload | null,
): string {
    if (!payload) {
        return 'Moonwalker is loading the latest memory snapshot.'
    }
    if (payload.stale) {
        return 'The last known trust board is still visible, but baseline Autopilot behavior is active until memory refreshes.'
    }
    if (payload.status === 'warming_up') {
        return `Learning from ${payload.warmup.current_closes} of ${payload.warmup.required_closes} closes before adaptive TP turns on.`
    }
    if (payload.status === 'fresh' && !payload.enabled) {
        return 'Moonwalker has enough history to rank symbols, but Autopilot is not applying it yet.'
    }
    if (payload.status === 'fresh') {
        return 'Moonwalker is using recent close quality and speed to adjust trust symbol by symbol.'
    }
    return 'Moonwalker needs closed-trade history before it can rank symbols.'
}

export function formatAutopilotMemoryHint(options: {
    currentCloses: number
    requiredCloses: number
    stale: boolean
    staleReason: string | null | undefined
    status: string | null | undefined
}): string {
    if (options.stale) {
        return `Memory stale: ${formatAutopilotReason(
            options.staleReason,
            null,
        )}`
    }
    if (options.status === 'warming_up') {
        return `Memory learning (${options.currentCloses}/${options.requiredCloses} closes)`
    }
    if (options.status === 'fresh') {
        return 'Memory ready'
    }
    return 'Memory idle'
}

export function formatAutopilotConfidenceBadge(bucket: string): string {
    if (bucket === 'confident') {
        return 'Confident'
    }
    if (bucket === 'usable') {
        return 'Usable'
    }
    return 'Warming up'
}

export function formatAutopilotTimestamp(
    timestamp: string | null | undefined,
): string {
    if (!timestamp) {
        return 'No timestamp yet'
    }
    const date = new Date(timestamp)
    if (Number.isNaN(date.getTime())) {
        return timestamp
    }
    return date.toLocaleString()
}
