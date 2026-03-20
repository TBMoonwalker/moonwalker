<script setup lang="ts">
import axios from 'axios'
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import { useMessage } from 'naive-ui/es/message'

import ConfigAutopilotSection from '../components/config/ConfigAutopilotSection.vue'
import ConfigDcaSection from '../components/config/ConfigDcaSection.vue'
import ConfigExchangeSection from '../components/config/ConfigExchangeSection.vue'
import ConfigFilterSection from '../components/config/ConfigFilterSection.vue'
import ConfigGeneralSection from '../components/config/ConfigGeneralSection.vue'
import ConfigIndicatorSection from '../components/config/ConfigIndicatorSection.vue'
import ConfigMonitoringSection from '../components/config/ConfigMonitoringSection.vue'
import ConfigSignalSection from '../components/config/ConfigSignalSection.vue'
import { MOONWALKER_API_ORIGIN } from '../config'
import { useSharedConfigSnapshot } from '../control-center/configSnapshotStore'
import { deriveGuidedFocusTarget } from '../control-center/focusFlow'
import type { OperationResult } from '../control-center/operationResults'
import { deriveControlCenterReadiness } from '../control-center/readiness'
import {
    buildControlCenterQuery,
    normalizeControlCenterRouteState,
} from '../control-center/routeState'
import { submitControlCenterWorkspace } from '../control-center/saveWorkflow'
import {
    getTaskPresentation,
    getTasksForMode,
    resolveTargetForConfigKey,
} from '../control-center/taskRegistry'
import type {
    ControlCenterBlocker,
    ControlCenterMode,
    ControlCenterTarget,
    ControlCenterTransitionIntent,
} from '../control-center/types'
import { deriveControlCenterViewState } from '../control-center/viewState'
import { waitForTargetElement } from '../control-center/focusFlow'
import { useConfigAdvancedGeneral } from '../composables/useConfigAdvancedGeneral'
import { useConfigBackupRestore } from '../composables/useConfigBackupRestore'
import { useConfigLoadFlow } from '../composables/useConfigLoadFlow'
import { useConfigMonitoringTest } from '../composables/useConfigMonitoringTest'
import { useConfigPageState } from '../composables/useConfigPageState'
import { useConfigPersistableState } from '../composables/useConfigPersistableState'
import { useConfigSaveFlow } from '../composables/useConfigSaveFlow'
import { useConfigSignalFlow } from '../composables/useConfigSignalFlow'
import { useConfigValidationFlow } from '../composables/useConfigValidationFlow'
import { buildConfigRules } from '../helpers/configRules'
import {
    buildConfigSubmitPayload,
    type ConfigSubmitPayloadDefaults,
} from '../helpers/configSubmitPayload'
import { trackUiEvent } from '../utils/uiTelemetry'

function getClientTimezone(): string {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
}

function extractAxiosErrorMessage(error: unknown, fallback: string): string {
    if (axios.isAxiosError(error)) {
        if (error.response?.data?.message) {
            return String(error.response.data.message)
        }
        if (error.response?.data?.error) {
            return String(error.response.data.error)
        }
        if (error.message) {
            return error.message
        }
    }
    if (error instanceof Error && error.message) {
        return error.message
    }
    return fallback
}

function normalizeBackendBlockers(rawBlockers: unknown): ControlCenterBlocker[] {
    if (!Array.isArray(rawBlockers)) {
        return []
    }

    return rawBlockers
        .map((blocker) => {
            if (!blocker || typeof blocker !== 'object') {
                return null
            }
            const key = String((blocker as { key?: unknown }).key ?? '').trim()
            const message = String(
                (blocker as { message?: unknown }).message ??
                    'Resolve this blocker before continuing.',
            ).trim()
            if (!key) {
                return null
            }
            const task = getTaskPresentation(resolveTargetForConfigKey(key))
            return {
                key,
                title: task.title,
                description: message,
                mode: task.defaultMode,
                target: task.target,
            } satisfies ControlCenterBlocker
        })
        .filter((blocker): blocker is ControlCenterBlocker => blocker !== null)
}

function createAnnouncement(message: string | null): string {
    return message ? message.trim() : ''
}

const route = useRoute()
const router = useRouter()
const message = useMessage()
const configSnapshotStore = useSharedConfigSnapshot()

const apiUrl = (path: string): string => new URL(path, MOONWALKER_API_ORIGIN).toString()
const isLoading = ref(true)
const activationLoading = ref(false)
const showAdvancedGeneral = ref(false)
const loadRescueMessage = ref<string | null>(null)
const staleDetected = ref(false)
const staleUpdatedAt = ref<string | null>(null)
const liveRegionMessage = ref('')
const transitionIntent = ref<ControlCenterTransitionIntent | null>(null)

let transitionTimeoutId: number | null = null
let staleCheckIntervalId: number | null = null

const ADVANCED_GENERAL_PREFERENCE_KEY = 'moonwalker.config.showAdvancedGeneral'
const STALE_CHECK_INTERVAL_MS = 15000
const ADVANCED_WS_HEALTHCHECK_INTERVAL_MS = 5000
const ADVANCED_WS_STALE_TIMEOUT_MS = 20000
const ADVANCED_WS_RECONNECT_DEBOUNCE_MS = 2000
const DEFAULT_SYMSIGNAL_URL = 'https://stream.3cqs.com'
const DEFAULT_SYMSIGNAL_VERSION = '3.0.1'
const DEFAULT_TP_SPIKE_CONFIRM_SECONDS = 3
const DEFAULT_TP_SPIKE_CONFIRM_TICKS = 0
const DEFAULT_GREEN_PHASE_RAMP_DAYS = 30
const DEFAULT_GREEN_PHASE_EVAL_INTERVAL_SEC = 60
const DEFAULT_GREEN_PHASE_WINDOW_MINUTES = 60
const DEFAULT_GREEN_PHASE_MIN_PROFITABLE_CLOSE_RATIO = 0.8
const DEFAULT_GREEN_PHASE_SPEED_MULTIPLIER = 1.5
const DEFAULT_GREEN_PHASE_EXIT_MULTIPLIER = 1.15
const DEFAULT_GREEN_PHASE_MAX_EXTRA_DEALS = 2
const DEFAULT_GREEN_PHASE_CONFIRM_CYCLES = 2
const DEFAULT_GREEN_PHASE_RELEASE_CYCLES = 4
const DEFAULT_GREEN_PHASE_MAX_LOCKED_FUND_PERCENT = 85

const configSubmitPayloadDefaults: ConfigSubmitPayloadDefaults = {
    advancedWsHealthcheckIntervalMs: ADVANCED_WS_HEALTHCHECK_INTERVAL_MS,
    advancedWsStaleTimeoutMs: ADVANCED_WS_STALE_TIMEOUT_MS,
    advancedWsReconnectDebounceMs: ADVANCED_WS_RECONNECT_DEBOUNCE_MS,
    defaultTpSpikeConfirmSeconds: DEFAULT_TP_SPIKE_CONFIRM_SECONDS,
    defaultTpSpikeConfirmTicks: DEFAULT_TP_SPIKE_CONFIRM_TICKS,
    defaultGreenPhaseRampDays: DEFAULT_GREEN_PHASE_RAMP_DAYS,
    defaultGreenPhaseEvalIntervalSec: DEFAULT_GREEN_PHASE_EVAL_INTERVAL_SEC,
    defaultGreenPhaseWindowMinutes: DEFAULT_GREEN_PHASE_WINDOW_MINUTES,
    defaultGreenPhaseMinProfitableCloseRatio:
        DEFAULT_GREEN_PHASE_MIN_PROFITABLE_CLOSE_RATIO,
    defaultGreenPhaseSpeedMultiplier: DEFAULT_GREEN_PHASE_SPEED_MULTIPLIER,
    defaultGreenPhaseExitMultiplier: DEFAULT_GREEN_PHASE_EXIT_MULTIPLIER,
    defaultGreenPhaseMaxExtraDeals: DEFAULT_GREEN_PHASE_MAX_EXTRA_DEALS,
    defaultGreenPhaseConfirmCycles: DEFAULT_GREEN_PHASE_CONFIRM_CYCLES,
    defaultGreenPhaseReleaseCycles: DEFAULT_GREEN_PHASE_RELEASE_CYCLES,
    defaultGreenPhaseMaxLockedFundPercent:
        DEFAULT_GREEN_PHASE_MAX_LOCKED_FUND_PERCENT,
}

const targetElements: Record<
    ControlCenterTarget,
    ReturnType<typeof ref<HTMLElement | null>>
> = {
    general: ref<HTMLElement | null>(null),
    exchange: ref<HTMLElement | null>(null),
    signal: ref<HTMLElement | null>(null),
    filter: ref<HTMLElement | null>(null),
    dca: ref<HTMLElement | null>(null),
    autopilot: ref<HTMLElement | null>(null),
    monitoring: ref<HTMLElement | null>(null),
    indicator: ref<HTMLElement | null>(null),
    'backup-restore': ref<HTMLElement | null>(null),
    'live-activation': ref<HTMLElement | null>(null),
}

function bindTargetElement(target: ControlCenterTarget) {
    return (element: Element | null) => {
        targetElements[target].value =
            element instanceof HTMLElement ? element : null
    }
}

const {
    autopilot,
    currency,
    dca,
    exchange,
    exchanges,
    filter,
    general,
    historyLookbackOptions,
    indicator,
    initializeTimezoneOptions,
    market,
    monitoring,
    resetSignalStrategySelection,
    sellOrderTypeOptions,
    signal,
    symsignals,
    timerange,
    timezone,
} = useConfigPageState({
    defaults: configSubmitPayloadDefaults,
})

const effectiveShowAdvancedGeneral = computed(
    () => showAdvancedGeneral.value || routeState.value.mode === 'advanced',
)

const { changedSectionLabels, changedSections, isDirty, syncBaselineState } =
    useConfigPersistableState({
        autopilot,
        dca,
        exchange,
        filter,
        general,
        indicator,
        monitoring,
        signal,
    })

const { buildConfigLoadDefaults } = useConfigAdvancedGeneral({
    advancedPreferenceKey: ADVANCED_GENERAL_PREFERENCE_KEY,
    defaultSymSignalUrl: DEFAULT_SYMSIGNAL_URL,
    defaultSymSignalVersion: DEFAULT_SYMSIGNAL_VERSION,
    defaults: configSubmitPayloadDefaults,
    general,
    getClientTimezone,
    isLoading,
    showAdvancedGeneral,
})

async function refreshWorkspaceFromSnapshot(force = false): Promise<OperationResult> {
    try {
        if (force) {
            await configSnapshotStore.refresh()
        } else {
            await configSnapshotStore.ensureLoaded(false)
        }
        const result = await fetchDefaultValues()
        loadRescueMessage.value = result.status === 'error' ? result.message : null
        staleDetected.value = false
        staleUpdatedAt.value = null
        if (result.status === 'success') {
            const normalizedState = normalizeControlCenterRouteState({
                requestedMode: routeState.value.mode,
                requestedTarget: routeState.value.target,
                fallbackMode: viewState.value.defaultMode,
            })
            await router.replace({
                name: 'controlCenter',
                query: buildControlCenterQuery(normalizedState),
            })
        }
        return result
    } catch (error) {
        const message = extractAxiosErrorMessage(
            error,
            'Failed to load configuration.',
        )
        loadRescueMessage.value = message
        return {
            status: 'error',
            message,
        }
    }
}

const {
    confirmDiscardUnsavedChanges,
    handleBeforeUnload,
    hasUnsavedChanges,
    isSubmitDisabled,
    resetSaveState,
    saveState,
    setSaveError,
    submitForm,
} = useConfigSaveFlow({
    apiUrl,
    buildPayload: () =>
        buildConfigSubmitPayload({
            general: general.value,
            signal: signal.value,
            filter: filter.value,
            exchange: exchange.value,
            dca: dca.value,
            autopilot: autopilot.value,
            monitoring: monitoring.value,
            indicator: indicator.value,
            showAdvancedGeneral: effectiveShowAdvancedGeneral.value,
            defaults: configSubmitPayloadDefaults,
        }),
    changedSectionLabels,
    changedSections,
    isDirty,
    isLoading,
    message,
    onSaved: async () => {
        await configSnapshotStore.refresh()
        const loadResult = await fetchDefaultValues()
        loadRescueMessage.value =
            loadResult.status === 'error' ? loadResult.message : null
    },
    surfaceMessages: false,
    syncBaselineState,
})

const {
    autopilotFormRef,
    dcaFormRef,
    exchangeFormRef,
    filterFormRef,
    generalFormRef,
    handleGlobalKeydown,
    indicatorFormRef,
    monitoringFormRef,
    signalFormRef,
    submitAttempted,
} = useConfigValidationFlow({
    message,
    onInvalid: async (sectionKey) => {
        const invalidTarget = sectionKey as ControlCenterTarget
        if (invalidTarget) {
            await guideToTarget(invalidTarget)
        }
    },
    onSubmitShortcut: handleSubmitWorkspace,
    onValidSubmit: handleSubmitWorkspace,
    setSaveError,
})

const {
    applySignalSettingsSelection,
    fetchAsapSymbolsForCurrency,
    getAsapMissingFieldsLabel,
    handleAsapUrlInput,
    handleCsvSignalFileSelected,
    handleSignalSettingsSelect,
    isAsapExchangeReady,
    isCurrencyConfigured,
    isUrlInput,
} = useConfigSignalFlow({
    apiUrl,
    defaultSymSignalUrl: DEFAULT_SYMSIGNAL_URL,
    defaultSymSignalVersion: DEFAULT_SYMSIGNAL_VERSION,
    exchange,
    isLoading,
    message,
    resetSignalStrategySelection,
    signal,
})

const {
    backupDownloadLoading,
    backupFileInputRef,
    backupIncludeTradeData,
    clearSelectedBackup,
    handleBackupDownload,
    handleBackupFileSelected,
    handleRestoreBackup,
    openBackupFilePicker,
    restoreLoading,
    selectedBackupConfigCount,
    selectedBackupFileName,
    selectedBackupHasTradeData,
    selectedBackupPayload,
} = useConfigBackupRestore({
    apiUrl,
    hasUnsavedChanges,
    message,
    onBeforeReload: () => {
        isLoading.value = true
    },
    reloadConfig: async () => {
        await configSnapshotStore.refresh()
        await fetchDefaultValues()
    },
    surfaceMessages: false,
})

const rules = buildConfigRules({
    dca,
    getAsapMissingFieldsLabel,
    isAsapExchangeReady,
    isCurrencyConfigured,
    isUrlInput,
    signal,
    submitAttempted,
})

const { fetchDefaultValues } = useConfigLoadFlow({
    apiUrl,
    buildDefaults: buildConfigLoadDefaults,
    loadConfig: async () => {
        const loadedConfig = await configSnapshotStore.ensureLoaded(false)
        return loadedConfig ?? configSnapshotStore.snapshot.value
    },
    general,
    signal,
    filter,
    exchange,
    dca,
    autopilot,
    monitoring,
    indicator,
    showAdvancedGeneral,
    isLoading,
    message,
    onAfterLoad: async () => {
        if (signal.value.strategy) {
            signal.value.strategy_enabled = true
        }
        await applySignalSettingsSelection({ awaitAsapFetch: true })
    },
    resetSaveState,
    setSaveError,
    surfaceMessages: false,
    syncBaselineState,
})

const {
    canTestMonitoringTelegram,
    monitoringTestLoading,
    testMonitoringTelegram,
} = useConfigMonitoringTest({
    apiUrl,
    message,
    monitoring,
    surfaceMessages: false,
})

const effectiveLoadError = computed(
    () => loadRescueMessage.value ?? configSnapshotStore.loadError.value,
)
const readiness = computed(() =>
    deriveControlCenterReadiness(configSnapshotStore.snapshot.value),
)
const visibleBlockers = computed(() => {
    if (
        transitionIntent.value?.status === 'blocked' &&
        transitionIntent.value.blockers &&
        transitionIntent.value.blockers.length > 0
    ) {
        return transitionIntent.value.blockers
    }
    return readiness.value.blockers
})
const viewState = computed(() =>
    deriveControlCenterViewState({
        loadError: effectiveLoadError.value,
        readiness: readiness.value,
        transition: transitionIntent.value,
    }),
)
const routeState = computed(() =>
    normalizeControlCenterRouteState({
        requestedMode: route.query.mode,
        requestedTarget: route.query.target,
        fallbackMode: viewState.value.defaultMode,
    }),
)

const advancedTasks = computed(() => getTasksForMode('advanced'))

const missionPrimaryLabel = computed(() => {
    if (!readiness.value.complete) {
        const nextTarget = readiness.value.nextTarget
        return nextTarget
            ? `Fix ${getTaskPresentation(nextTarget).title}`
            : 'Continue setup'
    }
    if (readiness.value.dryRun) {
        return 'Activate live trading'
    }
    return 'Review overview'
})

const missionSummaryTone = computed(() => {
    if (viewState.value.kind === 'rescue') {
        return 'error'
    }
    if (viewState.value.kind === 'attention_needed') {
        return 'warning'
    }
    if (viewState.value.kind === 'post_action_success') {
        return 'success'
    }
    if (viewState.value.kind === 'healthy') {
        return 'success'
    }
    return 'info'
})

const dirtySummary = computed(() => {
    if (!isDirty.value) {
        return 'No pending draft changes.'
    }
    return `Draft changes: ${changedSectionLabels.value.join(', ')}`
})

function announce(messageText: string | null): void {
    liveRegionMessage.value = ''
    const nextMessage = createAnnouncement(messageText)
    if (!nextMessage) {
        return
    }
    window.setTimeout(() => {
        liveRegionMessage.value = nextMessage
    }, 10)
}

function setTransitionIntent(nextIntent: ControlCenterTransitionIntent): void {
    transitionIntent.value = nextIntent
    if (transitionTimeoutId !== null) {
        window.clearTimeout(transitionTimeoutId)
        transitionTimeoutId = null
    }
    if (nextIntent.status === 'success') {
        transitionTimeoutId = window.setTimeout(() => {
            transitionIntent.value = null
            transitionTimeoutId = null
        }, 8000)
    }
}

async function navigateToControlCenter(
    mode: ControlCenterMode,
    target: ControlCenterTarget | null = null,
    replace = false,
): Promise<void> {
    const normalizedState = normalizeControlCenterRouteState({
        requestedMode: mode,
        requestedTarget: target,
        fallbackMode: mode,
    })
    const location = {
        name: 'controlCenter',
        query: buildControlCenterQuery(normalizedState),
    }
    if (replace) {
        await router.replace(location)
        return
    }
    await router.push(location)
}

async function focusTarget(target: ControlCenterTarget): Promise<boolean> {
    const element = await waitForTargetElement({
        nextTick,
        read: () => targetElements[target].value,
    })
    if (!element) {
        return false
    }
    element.scrollIntoView({
        behavior: 'auto',
        block: 'start',
    })
    const focusAnchor =
        element.querySelector<HTMLElement>('[data-control-center-anchor]') ??
        element
    focusAnchor.focus({ preventScroll: true })
    announce(deriveGuidedFocusTarget(target).announcement)
    return true
}

async function guideToTarget(target: ControlCenterTarget): Promise<void> {
    const task = getTaskPresentation(target)
    const requiresRouteTransition =
        routeState.value.mode !== task.defaultMode ||
        routeState.value.target !== target
    trackUiEvent('control_center_fix_this_requested', {
        target,
        mode: task.defaultMode,
    })
    await navigateToControlCenter(task.defaultMode, target)
    if (!requiresRouteTransition) {
        await focusTarget(target)
    }
}

async function handleModeSelect(mode: ControlCenterMode): Promise<void> {
    const currentTarget = routeState.value.target
    const nextTarget =
        currentTarget &&
        getTaskPresentation(currentTarget).modes.includes(mode)
            ? currentTarget
            : null
    await navigateToControlCenter(mode, nextTarget)
}

async function handleMissionPrimaryAction(): Promise<void> {
    if (!readiness.value.complete) {
        await guideToTarget(readiness.value.nextTarget ?? 'exchange')
        return
    }
    if (readiness.value.dryRun) {
        await handleActivateLiveTrading()
        return
    }
    await navigateToControlCenter('overview')
}

async function handleSubmitWorkspace(): Promise<void> {
    await submitControlCenterWorkspace({
        announce,
        navigateToMode: async (mode) => navigateToControlCenter(mode),
        normalizeBlockers: normalizeBackendBlockers,
        setTransitionIntent,
        submitForm,
    })
}

async function handleBackupDownloadAction(): Promise<void> {
    const result = await handleBackupDownload()
    if (result.status === 'success') {
        announce(result.message)
    } else if (result.status === 'error') {
        setTransitionIntent({
            kind: 'save',
            status: 'error',
            message: result.message,
            at: Date.now(),
        })
        announce(result.message)
    }
}

async function handleRestoreBackupAction(
    mode: 'config' | 'full',
): Promise<void> {
    const result = await handleRestoreBackup(mode)
    if (result.status === 'success') {
        await navigateToControlCenter('overview')
        setTransitionIntent({
            kind: 'restore',
            status: 'success',
            message: result.message,
            at: Date.now(),
            mode: 'overview',
        })
        announce(result.message)
        return
    }
    if (result.status === 'error') {
        setTransitionIntent({
            kind: 'restore',
            status: 'error',
            message: result.message,
            at: Date.now(),
        })
        announce(result.message)
    }
}

async function handleMonitoringTestAction(): Promise<void> {
    const result = await testMonitoringTelegram()
    if (result.status === 'success') {
        announce(result.message)
        return
    }
    if (result.status === 'error') {
        setTransitionIntent({
            kind: 'save',
            status: 'error',
            message: result.message,
            at: Date.now(),
        })
        announce(result.message)
    }
}

async function handleActivateLiveTrading(): Promise<void> {
    if (activationLoading.value) {
        return
    }
    if (isDirty.value) {
        const blockedMessage =
            'Save the current draft before activating live trading.'
        setTransitionIntent({
            kind: 'activate_live',
            status: 'blocked',
            message: blockedMessage,
            at: Date.now(),
        })
        announce(blockedMessage)
        return
    }
    if (!readiness.value.complete) {
        const blockedMessage =
            'Complete the required setup blockers before activating live trading.'
        setTransitionIntent({
            kind: 'activate_live',
            status: 'blocked',
            message: blockedMessage,
            at: Date.now(),
            blockers: readiness.value.blockers,
        })
        announce(blockedMessage)
        return
    }
    if (
        !window.confirm(
            'Activate live trading now? Moonwalker will stop simulating orders and submit them to the configured exchange.',
        )
    ) {
        return
    }

    activationLoading.value = true
    trackUiEvent('control_center_live_activation_requested')

    try {
        const response = await axios.post(apiUrl('/config/live/activate'), {
            confirm: true,
        })
        await configSnapshotStore.refresh()
        await fetchDefaultValues()
        await navigateToControlCenter('overview', 'live-activation')
        setTransitionIntent({
            kind: 'activate_live',
            status: 'success',
            message: response.data?.message || 'Live trading activated.',
            at: Date.now(),
            mode: 'overview',
            target: 'live-activation',
        })
        announce(response.data?.message || 'Live trading activated.')
    } catch (error) {
        const normalizedBlockers = normalizeBackendBlockers(
            axios.isAxiosError(error) ? error.response?.data?.blockers : undefined,
        )
        const status = axios.isAxiosError(error) && error.response?.status === 409
            ? 'blocked'
            : 'error'
        const messageText = extractAxiosErrorMessage(
            error,
            'Live activation failed.',
        )
        setTransitionIntent({
            kind: 'activate_live',
            status,
            message: messageText,
            at: Date.now(),
            blockers: normalizedBlockers,
            mode: normalizedBlockers[0]?.mode,
            target: normalizedBlockers[0]?.target,
        })
        announce(messageText)
    } finally {
        activationLoading.value = false
    }
}

async function handleReloadAfterStalePrompt(): Promise<void> {
    if (
        hasUnsavedChanges() &&
        !window.confirm(
            'Reload the newer configuration now and discard local draft changes?',
        )
    ) {
        return
    }
    const result = await refreshWorkspaceFromSnapshot(true)
    if (result.status === 'success') {
        setTransitionIntent({
            kind: 'retry',
            status: 'success',
            message: 'Loaded the latest configuration from another client.',
            at: Date.now(),
            mode: routeState.value.mode,
            target: routeState.value.target,
        })
        announce('Loaded the latest configuration from another client.')
    }
}

async function checkForExternalConfigChanges(): Promise<void> {
    if (document.hidden) {
        return
    }
    const freshness = await configSnapshotStore.checkFreshness()
    if (freshness.status !== 'stale') {
        return
    }
    staleDetected.value = true
    staleUpdatedAt.value = freshness.updatedAt
    if (!hasUnsavedChanges()) {
        await refreshWorkspaceFromSnapshot(true)
        announce('Configuration refreshed after external changes.')
        return
    }
    announce('A newer configuration is available from another client.')
}

watch(
    () => routeState.value.mode,
    (mode) => {
        if (mode === 'advanced') {
            showAdvancedGeneral.value = true
        }
    },
    { immediate: true },
)

watch(
    () => `${routeState.value.mode}:${routeState.value.target ?? ''}`,
    async () => {
        if (routeState.value.target) {
            await focusTarget(routeState.value.target)
        }
    },
    { flush: 'post' },
)

onBeforeRouteLeave(() => confirmDiscardUnsavedChanges('route_leave'))

onMounted(async () => {
    initializeTimezoneOptions(getClientTimezone())
    window.addEventListener('beforeunload', handleBeforeUnload)
    window.addEventListener('keydown', handleGlobalKeydown)
    window.addEventListener('focus', checkForExternalConfigChanges)
    staleCheckIntervalId = window.setInterval(
        checkForExternalConfigChanges,
        STALE_CHECK_INTERVAL_MS,
    )
    await refreshWorkspaceFromSnapshot(false)
    if (routeState.value.target) {
        await focusTarget(routeState.value.target)
    }
})

onUnmounted(() => {
    window.removeEventListener('beforeunload', handleBeforeUnload)
    window.removeEventListener('keydown', handleGlobalKeydown)
    window.removeEventListener('focus', checkForExternalConfigChanges)
    if (transitionTimeoutId !== null) {
        window.clearTimeout(transitionTimeoutId)
    }
    if (staleCheckIntervalId !== null) {
        window.clearInterval(staleCheckIntervalId)
    }
})
</script>

<template>
    <div class="page-shell control-center-page">
        <div class="sr-only" aria-live="polite" aria-atomic="true">
            {{ liveRegionMessage }}
        </div>

        <n-flex class="page-section" vertical>
            <n-card class="mission-panel" content-style="padding: 22px 24px;">
                <n-flex vertical :size="18">
                    <n-flex justify="space-between" align="center" :wrap="true">
                        <n-flex vertical :size="6">
                            <n-text depth="3" class="control-center-kicker">
                                Control Center
                            </n-text>
                            <div class="mission-heading-group">
                                <n-tag size="small" :type="missionSummaryTone">
                                    {{ viewState.badge }}
                                </n-tag>
                                <h1 class="mission-title">
                                    {{ viewState.title }}
                                </h1>
                            </div>
                            <n-text depth="3" class="mission-summary">
                                {{ viewState.summary }}
                            </n-text>
                        </n-flex>

                        <n-flex align="center" :wrap="true" :size="[10, 10]">
                            <n-button
                                v-if="isDirty"
                                type="primary"
                                secondary
                                :loading="saveState === 'saving'"
                                :disabled="isSubmitDisabled"
                                @click="handleSubmitWorkspace"
                            >
                                Save changes
                            </n-button>
                            <n-button
                                type="primary"
                                :loading="activationLoading"
                                :disabled="
                                    viewState.kind === 'rescue' ||
                                    (readiness.complete && readiness.dryRun
                                        ? activationLoading
                                        : false)
                                "
                                @click="handleMissionPrimaryAction"
                            >
                                {{ missionPrimaryLabel }}
                            </n-button>
                        </n-flex>
                    </n-flex>

                    <n-alert
                        :type="missionSummaryTone"
                        :title="dirtySummary"
                        role="status"
                        aria-live="polite"
                    >
                        <template v-if="transitionIntent">
                            {{ transitionIntent.message }}
                        </template>
                        <template v-else-if="staleDetected">
                            Another client changed this configuration
                            <span v-if="staleUpdatedAt">
                                at {{ new Date(staleUpdatedAt).toLocaleTimeString() }}.
                            </span>
                            Reload the latest snapshot before trusting this draft.
                        </template>
                        <template v-else>
                            {{
                                readiness.complete
                                    ? readiness.dryRun
                                        ? 'Moonwalker is configured for safe dry-run operation.'
                                        : 'Moonwalker is operating live on the configured exchange.'
                                    : `${visibleBlockers.length} setup item(s) still need attention.`
                            }}
                        </template>
                    </n-alert>

                    <n-flex
                        v-if="staleDetected"
                        class="stale-actions"
                        align="center"
                        :wrap="true"
                        :size="[10, 10]"
                    >
                        <n-button secondary type="warning" @click="handleReloadAfterStalePrompt">
                            Reload latest config
                        </n-button>
                        <n-text depth="3">
                            The shared snapshot changed in another browser or tab.
                        </n-text>
                    </n-flex>
                </n-flex>
            </n-card>
        </n-flex>

        <n-flex class="page-section" vertical>
            <n-card class="mode-strip-card" content-style="padding: 10px 12px;">
                <n-flex class="mode-strip" :wrap="true" :size="[10, 10]">
                    <n-button
                        :type="routeState.mode === 'overview' ? 'primary' : 'default'"
                        secondary
                        @click="handleModeSelect('overview')"
                    >
                        Overview
                    </n-button>
                    <n-button
                        :type="routeState.mode === 'setup' ? 'primary' : 'default'"
                        secondary
                        @click="handleModeSelect('setup')"
                    >
                        Setup
                    </n-button>
                    <n-button
                        :type="routeState.mode === 'advanced' ? 'primary' : 'default'"
                        secondary
                        @click="handleModeSelect('advanced')"
                    >
                        Advanced
                    </n-button>
                    <n-button
                        :type="routeState.mode === 'utilities' ? 'primary' : 'default'"
                        secondary
                        @click="handleModeSelect('utilities')"
                    >
                        Utilities
                    </n-button>
                </n-flex>
            </n-card>
        </n-flex>

        <n-flex class="page-section workspace-section" vertical>
            <template v-if="routeState.mode === 'overview'">
                <n-card class="workspace-card" content-style="padding: 18px 20px;">
                    <n-flex vertical :size="14">
                        <n-text depth="3">
                            {{
                                visibleBlockers.length > 0
                                    ? 'Targeted recovery cards'
                                    : 'Calm operator overview'
                            }}
                        </n-text>
                        <n-flex :wrap="true" :size="[14, 14]">
                            <n-card
                                v-for="blocker in visibleBlockers"
                                :key="blocker.key"
                                size="small"
                                class="status-card"
                            >
                                <n-flex vertical :size="10">
                                    <div>
                                        <h2 class="status-card-title">
                                            {{ blocker.title }}
                                        </h2>
                                        <n-text depth="3">
                                            {{ blocker.description }}
                                        </n-text>
                                    </div>
                                    <n-button
                                        type="primary"
                                        secondary
                                        @click="guideToTarget(blocker.target)"
                                    >
                                        Fix this
                                    </n-button>
                                </n-flex>
                            </n-card>

                            <template v-if="visibleBlockers.length === 0">
                                <n-card size="small" class="status-card">
                                    <n-flex vertical :size="10">
                                        <h2 class="status-card-title">Exchange connection</h2>
                                        <n-text depth="3">
                                            {{ exchange.name || 'Not configured' }} /
                                            {{ exchange.currency || 'No quote currency' }}
                                        </n-text>
                                        <n-button
                                            secondary
                                            @click="guideToTarget('exchange')"
                                        >
                                            Review exchange
                                        </n-button>
                                    </n-flex>
                                </n-card>

                                <n-card size="small" class="status-card">
                                    <n-flex vertical :size="10">
                                        <h2 class="status-card-title">Signal source</h2>
                                        <n-text depth="3">
                                            {{ signal.signal || 'Not configured' }}
                                        </n-text>
                                        <n-button
                                            secondary
                                            @click="guideToTarget('signal')"
                                        >
                                            Review signal source
                                        </n-button>
                                    </n-flex>
                                </n-card>

                                <div
                                    :ref="bindTargetElement('live-activation')"
                                    class="status-card"
                                    id="control-center-live-activation"
                                >
                                    <n-card size="small">
                                        <n-flex vertical :size="10">
                                            <div tabindex="-1" data-control-center-anchor>
                                                <h2 class="status-card-title">
                                                    {{ readiness.dryRun ? 'Trading mode: Dry run' : 'Trading mode: Live' }}
                                                </h2>
                                                <n-text depth="3">
                                                    {{
                                                        readiness.dryRun
                                                            ? 'Moonwalker is simulating orders. Use the guarded activation action to go live.'
                                                            : 'Moonwalker is submitting live orders to the configured exchange.'
                                                    }}
                                                </n-text>
                                            </div>
                                            <n-button
                                                v-if="readiness.dryRun"
                                                type="primary"
                                                secondary
                                                :loading="activationLoading"
                                                @click="handleActivateLiveTrading"
                                            >
                                                Activate live trading
                                            </n-button>
                                            <n-button
                                                v-else
                                                secondary
                                                @click="guideToTarget('exchange')"
                                            >
                                                Review safeguards
                                            </n-button>
                                        </n-flex>
                                    </n-card>
                                </div>
                            </template>
                        </n-flex>
                    </n-flex>
                </n-card>
            </template>

            <template v-else-if="routeState.mode === 'setup'">
                <div
                    :ref="bindTargetElement('general')"
                    class="task-section"
                    id="control-center-general"
                >
                    <div class="task-section-header" tabindex="-1" data-control-center-anchor>
                        <h2>{{ getTaskPresentation('general').title }}</h2>
                        <n-text depth="3">{{ getTaskPresentation('general').summary }}</n-text>
                    </div>
                    <ConfigGeneralSection
                        ref="generalFormRef"
                        :general="general"
                        :rules="rules"
                        :show-advanced-general="effectiveShowAdvancedGeneral"
                        :timezone="timezone"
                        @update:show-advanced-general="showAdvancedGeneral = $event"
                    />
                </div>

                <div
                    :ref="bindTargetElement('exchange')"
                    class="task-section"
                    id="control-center-exchange"
                >
                    <div class="task-section-header" tabindex="-1" data-control-center-anchor>
                        <h2>{{ getTaskPresentation('exchange').title }}</h2>
                        <n-text depth="3">{{ getTaskPresentation('exchange').summary }}</n-text>
                    </div>
                    <ConfigExchangeSection
                        ref="exchangeFormRef"
                        :currency="currency"
                        :exchange="exchange"
                        :exchanges="exchanges"
                        :market="market"
                        :rules="rules"
                        :show-advanced-general="effectiveShowAdvancedGeneral"
                        :timerange="timerange"
                    />
                </div>

                <div
                    :ref="bindTargetElement('signal')"
                    class="task-section"
                    id="control-center-signal"
                >
                    <div class="task-section-header" tabindex="-1" data-control-center-anchor>
                        <h2>{{ getTaskPresentation('signal').title }}</h2>
                        <n-text depth="3">{{ getTaskPresentation('signal').summary }}</n-text>
                    </div>
                    <ConfigSignalSection
                        ref="signalFormRef"
                        :asap-missing-fields-label="getAsapMissingFieldsLabel()"
                        :is-asap-exchange-ready="isAsapExchangeReady()"
                        :on-asap-url-input="handleAsapUrlInput"
                        :on-csv-file-selected="handleCsvSignalFileSelected"
                        :on-fetch-asap-symbols="fetchAsapSymbolsForCurrency"
                        :on-signal-settings-select="handleSignalSettingsSelect"
                        :rules="rules"
                        :signal="signal"
                        :symsignals="symsignals"
                    />
                </div>

                <div
                    :ref="bindTargetElement('dca')"
                    class="task-section"
                    id="control-center-dca"
                >
                    <div class="task-section-header" tabindex="-1" data-control-center-anchor>
                        <h2>{{ getTaskPresentation('dca').title }}</h2>
                        <n-text depth="3">{{ getTaskPresentation('dca').summary }}</n-text>
                    </div>
                    <ConfigDcaSection
                        ref="dcaFormRef"
                        :dca="dca"
                        :rules="rules"
                        :sell-order-type-options="sellOrderTypeOptions"
                        :show-advanced-general="effectiveShowAdvancedGeneral"
                        :strategy-options="signal.strategy_plugins"
                    />
                </div>

                <div
                    :ref="bindTargetElement('monitoring')"
                    class="task-section"
                    id="control-center-monitoring"
                >
                    <div class="task-section-header" tabindex="-1" data-control-center-anchor>
                        <h2>{{ getTaskPresentation('monitoring').title }}</h2>
                        <n-text depth="3">{{ getTaskPresentation('monitoring').summary }}</n-text>
                    </div>
                    <ConfigMonitoringSection
                        ref="monitoringFormRef"
                        :can-test="canTestMonitoringTelegram()"
                        :monitoring="monitoring"
                        :on-test="handleMonitoringTestAction"
                        :rules="rules"
                        :show-test-action="false"
                        :test-loading="monitoringTestLoading"
                    />
                </div>
            </template>

            <template v-else-if="routeState.mode === 'advanced'">
                <div
                    v-for="task in advancedTasks"
                    :id="task.sectionId"
                    :key="task.target"
                    :ref="bindTargetElement(task.target)"
                    class="task-section"
                >
                    <div class="task-section-header" tabindex="-1" data-control-center-anchor>
                        <h2>{{ task.title }}</h2>
                        <n-text depth="3">{{ task.summary }}</n-text>
                    </div>

                    <ConfigGeneralSection
                        v-if="task.target === 'general'"
                        ref="generalFormRef"
                        :general="general"
                        :rules="rules"
                        :show-advanced-general="true"
                        :timezone="timezone"
                        @update:show-advanced-general="showAdvancedGeneral = $event"
                    />
                    <ConfigExchangeSection
                        v-else-if="task.target === 'exchange'"
                        ref="exchangeFormRef"
                        :currency="currency"
                        :exchange="exchange"
                        :exchanges="exchanges"
                        :market="market"
                        :rules="rules"
                        :show-advanced-general="true"
                        :timerange="timerange"
                    />
                    <ConfigDcaSection
                        v-else-if="task.target === 'dca'"
                        ref="dcaFormRef"
                        :dca="dca"
                        :rules="rules"
                        :sell-order-type-options="sellOrderTypeOptions"
                        :show-advanced-general="true"
                        :strategy-options="signal.strategy_plugins"
                    />
                    <ConfigFilterSection
                        v-else-if="task.target === 'filter'"
                        ref="filterFormRef"
                        :filter="filter"
                        :rules="rules"
                        :show-asap-fields="signal.signal === 'asap'"
                    />
                    <ConfigAutopilotSection
                        v-else-if="task.target === 'autopilot'"
                        ref="autopilotFormRef"
                        :autopilot="autopilot"
                        :rules="rules"
                        :show-fields="autopilot.enabled"
                    />
                    <ConfigIndicatorSection
                        v-else-if="task.target === 'indicator'"
                        ref="indicatorFormRef"
                        :history-lookback-options="historyLookbackOptions"
                        :indicator="indicator"
                        :rules="rules"
                    />
                    <ConfigMonitoringSection
                        v-else-if="task.target === 'monitoring'"
                        ref="monitoringFormRef"
                        :can-test="canTestMonitoringTelegram()"
                        :monitoring="monitoring"
                        :on-test="handleMonitoringTestAction"
                        :rules="rules"
                        :show-test-action="false"
                        :test-loading="monitoringTestLoading"
                    />
                </div>
            </template>

            <template v-else>
                <div
                    :ref="bindTargetElement('backup-restore')"
                    class="task-section"
                    id="control-center-backup-restore"
                >
                    <div class="task-section-header" tabindex="-1" data-control-center-anchor>
                        <h2>{{ getTaskPresentation('backup-restore').title }}</h2>
                        <n-text depth="3">{{ getTaskPresentation('backup-restore').summary }}</n-text>
                    </div>
                    <n-card title="Backup & Restore" size="small">
                        <n-flex vertical :size="12">
                            <n-alert type="info" title="Portable backup">
                                Download configuration alone or include all trade data. Full restores
                                will repopulate the shared workspace after the backend finishes.
                            </n-alert>

                            <n-flex align="center" :wrap="true" :size="[12, 12]">
                                <n-checkbox v-model:checked="backupIncludeTradeData">
                                    Include trade data in backup
                                </n-checkbox>
                                <n-button
                                    type="primary"
                                    secondary
                                    :loading="backupDownloadLoading"
                                    @click="handleBackupDownloadAction"
                                >
                                    Download backup
                                </n-button>
                            </n-flex>

                            <n-divider />

                            <input
                                ref="backupFileInputRef"
                                type="file"
                                accept="application/json,.json"
                                class="backup-file-input"
                                @change="handleBackupFileSelected"
                            >

                            <n-flex align="center" :wrap="true" :size="[12, 12]">
                                <n-button secondary @click="openBackupFilePicker">
                                    Select backup file
                                </n-button>
                                <span v-if="selectedBackupFileName" class="backup-file-name">
                                    {{ selectedBackupFileName }}
                                </span>
                                <n-button
                                    v-if="selectedBackupFileName"
                                    quaternary
                                    @click="clearSelectedBackup"
                                >
                                    Clear
                                </n-button>
                            </n-flex>

                            <n-text v-if="selectedBackupPayload" depth="3">
                                Loaded backup with {{ selectedBackupConfigCount }} config keys<span v-if="selectedBackupHasTradeData"> and trade data</span>.
                            </n-text>

                            <n-flex align="center" :wrap="true" :size="[12, 12]">
                                <n-button
                                    type="warning"
                                    :loading="restoreLoading"
                                    :disabled="!selectedBackupPayload"
                                    @click="handleRestoreBackupAction('config')"
                                >
                                    Restore config only
                                </n-button>
                                <n-button
                                    type="error"
                                    ghost
                                    :loading="restoreLoading"
                                    :disabled="!selectedBackupHasTradeData"
                                    @click="handleRestoreBackupAction('full')"
                                >
                                    Restore full backup
                                </n-button>
                            </n-flex>
                        </n-flex>
                    </n-card>
                </div>

                <div class="task-section">
                    <div class="task-section-header">
                        <h2>Connectivity test</h2>
                        <n-text depth="3">
                            Run operational utility checks without mixing them into the config draft.
                        </n-text>
                    </div>
                    <n-card size="small">
                        <n-flex vertical :size="12">
                            <n-text depth="3">
                                Send a Telegram test using the currently saved monitoring configuration.
                            </n-text>
                            <n-flex align="center" :wrap="true" :size="[12, 12]">
                                <n-button
                                    secondary
                                    type="primary"
                                    :loading="monitoringTestLoading"
                                    :disabled="!canTestMonitoringTelegram()"
                                    @click="handleMonitoringTestAction"
                                >
                                    Test Telegram
                                </n-button>
                                <n-text depth="3">
                                    {{
                                        canTestMonitoringTelegram()
                                            ? 'Saved monitoring credentials are ready for a test message.'
                                            : 'Complete Telegram credentials in Setup or Advanced first.'
                                    }}
                                </n-text>
                            </n-flex>
                        </n-flex>
                    </n-card>
                </div>
            </template>
        </n-flex>
    </div>
</template>

<style scoped>
.control-center-page {
    gap: 0;
}

.page-section {
    margin-inline: 10px;
    margin-bottom: 10px;
}

.page-section:last-child {
    margin-bottom: 0;
}

.workspace-section {
    gap: 16px;
}

.control-center-kicker {
    font-size: 0.82rem;
    letter-spacing: 0.12em;
    text-transform: uppercase;
}

.mission-panel {
    border: 1px solid rgba(24, 65, 58, 0.18);
    background:
        radial-gradient(circle at top left, rgba(99, 226, 183, 0.18), transparent 34%),
        linear-gradient(135deg, rgba(18, 40, 37, 0.96), rgba(16, 24, 32, 0.96));
    color: rgba(255, 255, 255, 0.95);
}

.mission-heading-group {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 10px;
}

.mission-title {
    font-size: clamp(1.5rem, 3vw, 2.25rem);
    line-height: 1.1;
    font-weight: 700;
    letter-spacing: -0.02em;
}

.mission-summary {
    max-width: 72ch;
}

.mode-strip-card {
    border: 1px solid var(--color-border-hover);
}

.mode-strip {
    align-items: center;
}

.workspace-card,
.task-section {
    width: 100%;
}

.task-section {
    display: flex;
    flex-direction: column;
    gap: 10px;
}

.task-section-header {
    display: flex;
    flex-direction: column;
    gap: 4px;
}

.task-section-header h2,
.status-card-title {
    font-size: 1.05rem;
    font-weight: 700;
    letter-spacing: -0.01em;
}

.status-card {
    min-width: min(320px, 100%);
    flex: 1 1 280px;
}

.backup-file-input {
    display: none;
}

.backup-file-name {
    font-size: 14px;
}

.sr-only {
    position: absolute;
    width: 1px;
    height: 1px;
    padding: 0;
    margin: -1px;
    overflow: hidden;
    clip: rect(0, 0, 0, 0);
    white-space: nowrap;
    border: 0;
}

@media (max-width: 768px) {
    .page-section {
        margin-inline: 6px;
    }

    .mission-panel :deep(.n-alert) {
        padding-right: 0;
    }
}
</style>
