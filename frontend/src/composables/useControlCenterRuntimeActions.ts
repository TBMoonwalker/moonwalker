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
type RuntimeMutationOrigin =
    | RuntimeChangeOrigin
    | 'trading_pause'

interface ActivateLiveTradingResponse {
    data?: {
        message?: string
    }
}

interface ToggleTradingPauseResponse {
    data?: {
        message?: string
        status?: string
        trading_paused?: boolean
    }
}

interface UseControlCenterRuntimeActionsOptions {
    announce: (message: string | null) => void
    apiUrl: (path: string) => string
    hasUnsavedChanges: () => boolean
    isTradingPaused: ComputedRef<boolean>
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
        origin: RuntimeMutationOrigin,
    ) => Promise<OperationResult>
    confirmAction?: (message: string) => boolean
    postActivateRequest?: (
        url: string,
        payload: { confirm: true },
    ) => Promise<ActivateLiveTradingResponse>
    postTradingPauseRequest?: (
        url: string,
        payload: { confirm: true },
    ) => Promise<ToggleTradingPauseResponse>
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

async function defaultPostTradingPauseRequest(
    url: string,
    payload: { confirm: true },
): Promise<ToggleTradingPauseResponse> {
    return axios.post(url, payload)
}

function defaultTrackEvent(eventName: string): void {
    trackUiEvent(eventName)
}

export function useControlCenterRuntimeActions(
    options: UseControlCenterRuntimeActionsOptions,
) {
    const activationLoading = ref(false)
    const tradingPauseLoading = ref(false)
    const confirmAction = options.confirmAction ?? defaultConfirmAction
    const postActivateRequest =
        options.postActivateRequest ?? defaultPostActivateRequest
    const postTradingPauseRequest =
        options.postTradingPauseRequest ?? defaultPostTradingPauseRequest
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

    async function handleToggleTradingPause(): Promise<void> {
        if (tradingPauseLoading.value) {
            return
        }
        if (options.isDirty.value) {
            const blockedMessage =
                'Save the current draft before changing Moonwalker pause state.'
            options.setTransitionIntent({
                kind: 'toggle_trading_pause',
                status: 'blocked',
                message: blockedMessage,
                at: Date.now(),
            })
            options.announce(blockedMessage)
            return
        }

        const nextAction = options.isTradingPaused.value ? 'resume' : 'pause'
        const confirmMessage = options.isTradingPaused.value
            ? 'Resume Moonwalker now? New trades and re-entries will be allowed again after this confirmation.'
            : 'Pause Moonwalker now? Existing exits can keep running, but no new trades or re-entries will be allowed until you resume.'
        if (!confirmAction(confirmMessage)) {
            return
        }

        tradingPauseLoading.value = true
        trackEvent(
            nextAction === 'pause'
                ? 'control_center_trading_pause_requested'
                : 'control_center_trading_resume_requested',
        )

        try {
            const response = await postTradingPauseRequest(
                options.apiUrl(`/config/trading/${nextAction}`),
                {
                    confirm: true,
                },
            )
            const syncResult = await options.syncControlCenterConfigChange(
                'trading_pause',
            )
            if (syncResult.status === 'error') {
                throw new Error(syncResult.message)
            }
            const successMessage =
                response.data?.message ??
                (nextAction === 'pause'
                    ? 'Moonwalker paused for new exposure.'
                    : 'Moonwalker resumed for new exposure.')
            options.setTransitionIntent({
                kind: 'toggle_trading_pause',
                status: 'success',
                message: successMessage,
                at: Date.now(),
                mode: options.routeState.value.mode,
                target: options.routeState.value.target,
            })
            options.announce(successMessage)
        } catch (error) {
            const status =
                axios.isAxiosError(error) && error.response?.status === 409
                    ? 'blocked'
                    : 'error'
            const messageText = extractApiErrorMessage(
                error,
                'Trading pause change failed.',
            )
            options.setTransitionIntent({
                kind: 'toggle_trading_pause',
                status,
                message: messageText,
                at: Date.now(),
                mode: options.routeState.value.mode,
                target: options.routeState.value.target,
            })
            options.announce(messageText)
        } finally {
            tradingPauseLoading.value = false
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
        handleToggleTradingPause,
        tradingPauseLoading,
    }
}
