import type { OperationResult } from './operationResults'
import type {
    ControlCenterBlocker,
    ControlCenterMode,
    ControlCenterTransitionIntent,
} from './types'

interface SubmitControlCenterWorkspaceOptions {
    announce: (message: string) => void
    navigateToMode: (mode: ControlCenterMode) => Promise<void>
    normalizeBlockers: (rawBlockers: unknown) => ControlCenterBlocker[]
    now?: () => number
    setTransitionIntent: (intent: ControlCenterTransitionIntent) => void
    submitForm: () => Promise<OperationResult>
}

export async function submitControlCenterWorkspace(
    options: SubmitControlCenterWorkspaceOptions,
): Promise<OperationResult> {
    const result = await options.submitForm()
    const at = (options.now ?? Date.now)()

    if (result.status === 'success') {
        await options.navigateToMode('overview')
        options.setTransitionIntent({
            kind: 'save',
            status: 'success',
            message: 'Configuration saved.',
            at,
            mode: 'overview',
        })
        options.announce('Configuration saved.')
        return result
    }

    if (result.status === 'blocked') {
        options.setTransitionIntent({
            kind: 'save',
            status: 'blocked',
            message: result.message,
            at,
            blockers: options.normalizeBlockers(result.blockers),
        })
        options.announce(result.message)
        return result
    }

    if (result.status === 'error') {
        options.setTransitionIntent({
            kind: 'save',
            status: 'error',
            message: result.message,
            at,
        })
        options.announce(result.message)
    }

    return result
}
