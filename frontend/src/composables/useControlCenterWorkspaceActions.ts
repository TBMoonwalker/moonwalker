import type { OperationResult } from '../control-center/operationResults'
import { submitControlCenterWorkspace } from '../control-center/saveWorkflow'
import type {
    ControlCenterBlocker,
    ControlCenterMode,
    ControlCenterTransitionIntent,
} from '../control-center/types'

type BackupRestoreMode = 'config' | 'full'

interface UseControlCenterWorkspaceActionsOptions {
    announce: (message: string | null) => void
    handleBackupDownload: () => Promise<OperationResult>
    handleRestoreBackup: (
        mode: BackupRestoreMode,
    ) => Promise<OperationResult>
    navigateToControlCenter: (
        mode: ControlCenterMode,
    ) => Promise<void>
    normalizeBlockers: (rawBlockers: unknown) => ControlCenterBlocker[]
    now?: () => number
    setTransitionIntent: (nextIntent: ControlCenterTransitionIntent) => void
    submitForm: () => Promise<OperationResult>
    testMonitoringTelegram: () => Promise<OperationResult>
}

function buildTransitionAt(
    now: (() => number) | undefined,
): number {
    return (now ?? Date.now)()
}

export function useControlCenterWorkspaceActions(
    options: UseControlCenterWorkspaceActionsOptions,
) {
    async function handleSubmitWorkspace(): Promise<void> {
        await submitControlCenterWorkspace({
            announce: (message) => options.announce(message),
            navigateToMode: async (mode) => options.navigateToControlCenter(mode),
            normalizeBlockers: options.normalizeBlockers,
            now: options.now,
            setTransitionIntent: options.setTransitionIntent,
            submitForm: options.submitForm,
        })
    }

    async function handleBackupDownloadAction(): Promise<void> {
        const result = await options.handleBackupDownload()
        if (result.status === 'success') {
            options.announce(result.message)
        } else if (result.status === 'error') {
            options.setTransitionIntent({
                kind: 'save',
                status: 'error',
                message: result.message,
                at: buildTransitionAt(options.now),
            })
            options.announce(result.message)
        }
    }

    async function handleRestoreBackupAction(
        mode: BackupRestoreMode,
    ): Promise<void> {
        const result = await options.handleRestoreBackup(mode)
        if (result.status === 'success') {
            await options.navigateToControlCenter('overview')
            options.setTransitionIntent({
                kind: 'restore',
                status: 'success',
                message: result.message,
                at: buildTransitionAt(options.now),
                mode: 'overview',
            })
            options.announce(result.message)
            return
        }
        if (result.status === 'error') {
            options.setTransitionIntent({
                kind: 'restore',
                status: 'error',
                message: result.message,
                at: buildTransitionAt(options.now),
            })
            options.announce(result.message)
        }
    }

    async function handleMonitoringTestAction(): Promise<void> {
        const result = await options.testMonitoringTelegram()
        if (result.status === 'success') {
            options.announce(result.message)
            return
        }
        if (result.status === 'error') {
            options.setTransitionIntent({
                kind: 'save',
                status: 'error',
                message: result.message,
                at: buildTransitionAt(options.now),
            })
            options.announce(result.message)
        }
    }

    return {
        handleBackupDownloadAction,
        handleMonitoringTestAction,
        handleRestoreBackupAction,
        handleSubmitWorkspace,
    }
}
