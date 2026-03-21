import type { RouteLocationNormalized } from 'vue-router'

import { getTaskPresentation, isKnownControlCenterTarget } from './taskRegistry'
import { type ControlCenterReadiness } from './types'
import { buildControlCenterQuery, normalizeControlCenterRouteState } from './routeState'
import { deriveControlCenterViewState } from './viewState'

function areQueriesEqual(
    currentRoute: RouteLocationNormalized,
    nextQuery: Record<string, string>,
): boolean {
    const currentMode = currentRoute.query.mode
    const currentTarget = currentRoute.query.target
    const normalizedCurrentMode =
        typeof currentMode === 'string' ? currentMode : null
    const normalizedCurrentTarget =
        typeof currentTarget === 'string' ? currentTarget : null

    return (
        normalizedCurrentMode === (nextQuery.mode ?? null) &&
        normalizedCurrentTarget === (nextQuery.target ?? null)
    )
}

export function resolveControlCenterNavigation(
    to: RouteLocationNormalized,
    options: {
        loadError: string | null
        readiness: ControlCenterReadiness
    },
): Record<string, unknown> | true {
    if (!options.loadError && !options.readiness.complete) {
        const rawTarget = Array.isArray(to.query.target)
            ? to.query.target[0]
            : to.query.target
        const requestedTarget = isKnownControlCenterTarget(rawTarget)
            ? rawTarget
            : null
        const nextTarget =
            requestedTarget &&
            getTaskPresentation(requestedTarget).modes.includes('setup')
                ? requestedTarget
                : options.readiness.nextTarget
        const normalizedQuery = buildControlCenterQuery({
            mode: 'setup',
            target: nextTarget,
        })

        if (to.name === 'controlCenter' && areQueriesEqual(to, normalizedQuery)) {
            return true
        }

        return {
            name: 'controlCenter',
            query: normalizedQuery,
            replace: true,
        }
    }

    if (to.name === 'controlCenter') {
        const viewState = deriveControlCenterViewState({
            loadError: options.loadError,
            readiness: options.readiness,
            transition: null,
        })
        const normalizedRouteState = normalizeControlCenterRouteState({
            requestedMode: to.query.mode,
            requestedTarget: to.query.target,
            fallbackMode: viewState.defaultMode,
        })
        const normalizedQuery = buildControlCenterQuery(normalizedRouteState)
        if (areQueriesEqual(to, normalizedQuery)) {
            return true
        }
        return {
            name: 'controlCenter',
            query: normalizedQuery,
            replace: true,
        }
    }

    return true
}
