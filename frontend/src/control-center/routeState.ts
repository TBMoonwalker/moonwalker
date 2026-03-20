import {
    getTaskPresentation,
    isKnownControlCenterTarget,
} from './taskRegistry'
import {
    CONTROL_CENTER_MODES,
    type ControlCenterMode,
    type ControlCenterRouteState,
    type ControlCenterTarget,
} from './types'

function normalizeQueryValue(value: unknown): string | null {
    if (typeof value === 'string') {
        return value.trim() || null
    }
    if (Array.isArray(value)) {
        const firstValue = value[0]
        return typeof firstValue === 'string' ? firstValue.trim() || null : null
    }
    return null
}

export function isKnownControlCenterMode(
    value: unknown,
): value is ControlCenterMode {
    return (
        typeof value === 'string' &&
        CONTROL_CENTER_MODES.includes(value as ControlCenterMode)
    )
}

export function normalizeControlCenterRouteState(options: {
    requestedMode?: unknown
    requestedTarget?: unknown
    fallbackMode: ControlCenterMode
}): ControlCenterRouteState {
    const rawTarget = normalizeQueryValue(options.requestedTarget)
    const rawMode = normalizeQueryValue(options.requestedMode)
    const target = isKnownControlCenterTarget(rawTarget) ? rawTarget : null
    const requestedMode = isKnownControlCenterMode(rawMode)
        ? rawMode
        : options.fallbackMode

    if (!target) {
        return {
            mode: requestedMode,
            target: null,
        }
    }

    const task = getTaskPresentation(target)
    if (task.modes.includes(requestedMode)) {
        return {
            mode: requestedMode,
            target,
        }
    }

    return {
        mode: task.defaultMode,
        target,
    }
}

export function buildControlCenterQuery(
    routeState: ControlCenterRouteState,
): Record<string, string> {
    const query: Record<string, string> = {
        mode: routeState.mode,
    }
    if (routeState.target) {
        query.target = routeState.target
    }
    return query
}

export function buildLegacyControlCenterRedirect(query: Record<string, unknown>): {
    name: 'controlCenter'
    query: Record<string, string>
} {
    const requestedTarget = normalizeQueryValue(query.target)
    const routeState = normalizeControlCenterRouteState({
        requestedMode: query.mode ?? (query.setup ? 'setup' : 'setup'),
        requestedTarget,
        fallbackMode: 'setup',
    })

    return {
        name: 'controlCenter',
        query: buildControlCenterQuery(routeState),
    }
}
