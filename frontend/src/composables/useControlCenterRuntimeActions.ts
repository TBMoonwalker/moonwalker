import axios from 'axios'
import { ref, type ComputedRef } from 'vue'

import type { OperationResult } from '../control-center/operationResults'
import type {
    ConfigFreshnessPayload,
    ControlCenterBlocker,
    ControlCenterReadiness,
    ControlCenterRouteState,
    ControlCenterTarget,
    ControlCenterTransitionIntent,
} from '../control-center/types'
import { extractApiErrorMessage } from '../helpers/apiErrors'
import { trackUiEvent } from '../utils/uiTelemetry'

type RuntimeFreshnessStatus = 'unchanged' | 'stale' | 'unknown'

interface RuntimeSnapshotStoreLike {
    checkFreshness: () => Promise<{
        status: RuntimeFreshnessStatus
        updatedAt: ConfigFreshnessPayload['updated_at']
    }>
}

type RuntimeChangeOrigin = 'live_activation' | 'external_invalidation'

interface ActivateLiveTradingResponse {
    data?: {
        message?: string
    }
}

interface UseControlCenterRuntimeActionsOptions {
    announce: (message: string | null) => void
    apiUrl: (path: string) => string
    hasUnsavedChanges: () => boolean
    isDirty: ComputedRef<boolean>
    navigateToControlCenter: (
        mode: ControlCenterRouteState['mode'],
        target?: ControlCenterTarget | null,
    ) => Promise<void>
    normalizeBlockers: (rawBlockers: unknown) => ControlCenterBlocker[]
    readiness: ComputedRef<ControlCenterReadiness>
    routeState: ComputedRef<ControlCenterRouteState>
    setTransitionIntent: (nextIntent: ControlCenterTransitionIntent) => void
    snapshotStore: RuntimeSnapshotStoreLike
    syncControlCenterConfigChange: (
        origin: RuntimeChangeOrigin,
    ) => Promise<OperationResult>
    confirmAction?: (message: string) => boolean
    postActivateRequest?: (
        url: string,
        payload: { confirm: true },
    ) => Promise<ActivateLiveTradingResponse>
    trackEvent?: (eventName: string) => void
}

function defaultConfirmAction(message: string): boolean {
    return window.confirm(message)
}

async function defaultPostActivateRequest(
    url: string,
    payload: { confirm: true },
): Promise<ActivateLiveTradingResponse> {
    return axios.post(url, payload)
}

function defaultTrackEvent(eventName: string): void {
    trackUiEvent(eventName)
}

export function useControlCenterRuntimeActions(
    options: UseControlCenterRuntimeActionsOptions,
) {
    const activationLoading = ref(false)
    const confirmAction = options.confirmAction ?? defaultConfirmAction
    const postActivateRequest =
        options.postActivateRequest ?? defaultPostActivateRequest
    const trackEvent = options.trackEvent ?? defaultTrackEvent

    async function handleActivateLiveTrading(): Promise<void> {
        if (activationLoading.value) {
            return
        }
        if (options.isDirty.value) {
            const blockedMessage =
                'Save the current draft before activating live trading.'
            options.setTransitionIntent({
                kind: 'activate_live',
                status: 'blocked',
                message: blockedMessage,
                at: Date.now(),
            })
            options.announce(blockedMessage)
            return
        }
        if (!options.readiness.value.complete) {
            const blockedMessage =
                'Complete the required setup blockers before activating live trading.'
            options.setTransitionIntent({
                kind: 'activate_live',
                status: 'blocked',
                message: blockedMessage,
                at: Date.now(),
                blockers: options.readiness.value.blockers,
            })
            options.announce(blockedMessage)
            return
        }
        if (
            !confirmAction(
                'Activate live trading now? Moonwalker will stop simulating orders and submit them to the configured exchange.',
            )
        ) {
            return
        }

        activationLoading.value = true
        trackEvent('control_center_live_activation_requested')

        try {
            const response = await postActivateRequest(
                options.apiUrl('/config/live/activate'),
                {
                    confirm: true,
                },
            )
            const syncResult = await options.syncControlCenterConfigChange(
                'live_activation',
            )
            if (syncResult.status === 'error') {
                throw new Error(syncResult.message)
            }
            await options.navigateToControlCenter('overview', 'live-activation')
            const successMessage =
                response.data?.message || 'Live trading activated.'
            options.setTransitionIntent({
                kind: 'activate_live',
                status: 'success',
                message: successMessage,
                at: Date.now(),
                mode: 'overview',
                target: 'live-activation',
            })
            options.announce(successMessage)
        } catch (error) {
            const normalizedBlockers = options.normalizeBlockers(
                axios.isAxiosError(error)
                    ? error.response?.data?.blockers
                    : undefined,
            )
            const status =
                axios.isAxiosError(error) && error.response?.status === 409
                    ? 'blocked'
                    : 'error'
            const messageText = extractApiErrorMessage(
                error,
                'Live activation failed.',
            )
            options.setTransitionIntent({
                kind: 'activate_live',
                status,
                message: messageText,
                at: Date.now(),
                blockers: normalizedBlockers,
                mode: normalizedBlockers[0]?.mode,
                target: normalizedBlockers[0]?.target,
            })
            options.announce(messageText)
        } finally {
            activationLoading.value = false
        }
    }

    async function handleReloadAfterStalePrompt(): Promise<void> {
        if (
            options.hasUnsavedChanges() &&
            !confirmAction(
                'Reload the newer configuration now and discard local draft changes?',
            )
        ) {
            return
        }
        const result = await options.syncControlCenterConfigChange(
            'external_invalidation',
        )
        if (result.status === 'success') {
            options.setTransitionIntent({
                kind: 'retry',
                status: 'success',
                message: 'Loaded the latest configuration from another client.',
                at: Date.now(),
                mode: options.routeState.value.mode,
                target: options.routeState.value.target,
            })
            options.announce('Loaded the latest configuration from another client.')
        }
    }

    async function handleDetectedExternalConfigChange(
        shouldAnnounce =
            typeof document === 'undefined' ? true : !document.hidden,
    ): Promise<void> {
        if (!options.hasUnsavedChanges()) {
            const result = await options.syncControlCenterConfigChange(
                'external_invalidation',
            )
            if (shouldAnnounce) {
                options.announce(
                    result.status === 'success'
                        ? 'Configuration refreshed after external changes.'
                        : result.message,
                )
            }
            return
        }

        if (shouldAnnounce) {
            options.announce('A newer configuration is available from another client.')
        }
    }

    async function checkForExternalConfigChanges(): Promise<void> {
        if (typeof document !== 'undefined' && document.hidden) {
            return
        }
        const freshness = await options.snapshotStore.checkFreshness()
        if (freshness.status !== 'stale') {
            return
        }
        await handleDetectedExternalConfigChange(true)
    }

    return {
        activationLoading,
        checkForExternalConfigChanges,
        handleActivateLiveTrading,
        handleDetectedExternalConfigChange,
        handleReloadAfterStalePrompt,
    }
}
