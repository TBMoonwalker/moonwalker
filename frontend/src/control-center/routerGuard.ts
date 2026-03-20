import type { RouteLocationNormalized } from 'vue-router'

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

    if (!options.loadError && !options.readiness.complete) {
        return {
            name: 'controlCenter',
            query: buildControlCenterQuery({
                mode: 'setup',
                target: options.readiness.nextTarget,
            }),
        }
    }

    return true
}
