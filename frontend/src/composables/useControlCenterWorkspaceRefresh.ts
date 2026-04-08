import type { Ref } from 'vue'

import type { OperationResult } from '../control-center/operationResults'
import {
    buildControlCenterQuery,
    normalizeControlCenterRouteState,
} from '../control-center/routeState'
import type {
    ControlCenterRouteState,
    ControlCenterViewState,
} from '../control-center/types'
import { extractApiErrorMessage } from '../helpers/apiErrors'

interface SnapshotStoreLike {
    ensureLoaded: (force?: boolean) => Promise<unknown>
    refresh: () => Promise<unknown>
}

interface ControlCenterRouterLike {
    replace: (location: {
        name: 'controlCenter'
        query: Record<string, string>
    }) => Promise<unknown>
}

interface UseControlCenterWorkspaceRefreshOptions {
    fetchDefaultValues: () => Promise<OperationResult>
    loadRescueMessage: Ref<string | null>
    readRouteState: () => ControlCenterRouteState
    readViewState: () => ControlCenterViewState
    router: ControlCenterRouterLike
    snapshotStore: SnapshotStoreLike
}

export function useControlCenterWorkspaceRefresh(
    options: UseControlCenterWorkspaceRefreshOptions,
) {
    async function refreshWorkspaceFromSnapshot(
        force = false,
    ): Promise<OperationResult> {
        try {
            if (force) {
                await options.snapshotStore.refresh()
            } else {
                await options.snapshotStore.ensureLoaded(false)
            }

            const result = await options.fetchDefaultValues()
            options.loadRescueMessage.value =
                result.status === 'error' ? result.message : null

            if (result.status === 'success') {
                const routeState = options.readRouteState()
                const viewState = options.readViewState()
                const normalizedState = normalizeControlCenterRouteState({
                    requestedMode: routeState.mode,
                    requestedTarget: routeState.target,
                    fallbackMode: viewState.defaultMode,
                })

                await options.router.replace({
                    name: 'controlCenter',
                    query: buildControlCenterQuery(normalizedState),
                })
            }

            return result
        } catch (error) {
            const message = extractApiErrorMessage(
                error,
                'Failed to load configuration.',
            )
            options.loadRescueMessage.value = message
            return {
                status: 'error',
                message,
            }
        }
    }

    return {
        refreshWorkspaceFromSnapshot,
    }
}
