import type { OperationResult } from './operationResults'
import type { ControlCenterConfigChangeOrigin } from './types'

type LocalConfigChangeOrigin = Exclude<
    ControlCenterConfigChangeOrigin,
    'external_invalidation'
>

interface CreateControlCenterConfigChangeSynchronizerOptions {
    emitInvalidation: (origin: LocalConfigChangeOrigin) => void
    refreshWorkspace: (force?: boolean) => Promise<OperationResult>
}

export function createControlCenterConfigChangeSynchronizer(
    options: CreateControlCenterConfigChangeSynchronizerOptions,
) {
    let pendingSync: Promise<OperationResult> | null = null

    return async function syncControlCenterConfigChange(
        origin: ControlCenterConfigChangeOrigin,
    ): Promise<OperationResult> {
        if (pendingSync) {
            return pendingSync
        }

        pendingSync = (async () => {
            const result = await options.refreshWorkspace(true)
            if (result.status === 'success' && origin !== 'external_invalidation') {
                options.emitInvalidation(origin)
            }
            return result
        })()

        try {
            return await pendingSync
        } finally {
            pendingSync = null
        }
    }
}
