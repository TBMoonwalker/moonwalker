<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import { useMessage } from 'naive-ui/es/message'

import ConfigAutopilotSection from '../components/config/ConfigAutopilotSection.vue'
import ConfigDcaAdvancedSection from '../components/config/ConfigDcaAdvancedSection.vue'
import ConfigDcaSection from '../components/config/ConfigDcaSection.vue'
import ConfigExchangeAdvancedSection from '../components/config/ConfigExchangeAdvancedSection.vue'
import ConfigExchangeSection from '../components/config/ConfigExchangeSection.vue'
import ConfigFilterSection from '../components/config/ConfigFilterSection.vue'
import ConfigGeneralAdvancedSection from '../components/config/ConfigGeneralAdvancedSection.vue'
import ConfigGeneralSection from '../components/config/ConfigGeneralSection.vue'
import ConfigIndicatorSection from '../components/config/ConfigIndicatorSection.vue'
import ConfigMonitoringSection from '../components/config/ConfigMonitoringSection.vue'
import ConfigSignalSection from '../components/config/ConfigSignalSection.vue'
import { MOONWALKER_API_ORIGIN } from '../config'
import { createControlCenterConfigChangeSynchronizer } from '../control-center/configChangeSync'
import { useSharedConfigSnapshot } from '../control-center/configSnapshotStore'
import {
    getTaskPresentation,
    resolveTargetForConfigKey,
} from '../control-center/taskRegistry'
import type {
    ControlCenterBlocker,
    ControlCenterTarget,
} from '../control-center/types'
import { useConfigAdvancedGeneral } from '../composables/useConfigAdvancedGeneral'
import { useConfigBackupRestore } from '../composables/useConfigBackupRestore'
import { useConfigLoadFlow } from '../composables/useConfigLoadFlow'
import { useConfigMonitoringTest } from '../composables/useConfigMonitoringTest'
import { useConfigPageState } from '../composables/useConfigPageState'
import { useConfigPersistableState } from '../composables/useConfigPersistableState'
import { useControlCenterDerivedState } from '../composables/useControlCenterDerivedState'
import { useControlCenterFeedback } from '../composables/useControlCenterFeedback'
import { useControlCenterMissionState } from '../composables/useControlCenterMissionState'
import { useControlCenterNavigation } from '../composables/useControlCenterNavigation'
import { useControlCenterRuntimeActions } from '../composables/useControlCenterRuntimeActions'
import { useControlCenterSetupFlow } from '../composables/useControlCenterSetupFlow'
import { useControlCenterWorkspaceRefresh } from '../composables/useControlCenterWorkspaceRefresh'
import { useControlCenterWorkspaceActions } from '../composables/useControlCenterWorkspaceActions'
import { useConfigSaveFlow } from '../composables/useConfigSaveFlow'
import { useConfigSignalFlow } from '../composables/useConfigSignalFlow'
import { useConfigValidationFlow } from '../composables/useConfigValidationFlow'
import { buildConfigRules } from '../helpers/configRules'
import {
    buildConfigSubmitPayload,
    type ConfigSubmitPayloadDefaults,
} from '../helpers/configSubmitPayload'

function getClientTimezone(): string {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
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

const route = useRoute()
const router = useRouter()
const message = useMessage()
const configSnapshotStore = useSharedConfigSnapshot()

const apiUrl = (path: string): string => new URL(path, MOONWALKER_API_ORIGIN).toString()
const isLoading = ref(true)
const showAdvancedGeneral = ref(false)
const loadRescueMessage = ref<string | null>(null)

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
            showAdvancedGeneral:
                routeState.value.mode === 'advanced' ||
                setupShowsAdvancedFields.value,
            defaults: configSubmitPayloadDefaults,
        }),
    changedSectionLabels,
    changedSections,
    isDirty,
    isLoading,
    message,
    onSaved: async () => {
        const result = await syncControlCenterConfigChange('save')
        if (result.status === 'error') {
            throw new Error(result.message)
        }
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
        const result = await syncControlCenterConfigChange('restore')
        if (result.status === 'error') {
            throw new Error(result.message)
        }
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

const syncControlCenterConfigChange = createControlCenterConfigChangeSynchronizer({
    emitInvalidation: (origin) => {
        configSnapshotStore.emitLocalInvalidation(origin)
    },
    refreshWorkspace: (force) => refreshWorkspaceFromSnapshot(force),
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

const {
    announce,
    disposeFeedback,
    liveRegionMessage,
    setTransitionIntent,
    transitionIntent,
} = useControlCenterFeedback()
const {
    configTrustState,
    effectiveLoadError,
    readiness,
    routeState,
    viewState,
    visibleBlockers,
} = useControlCenterDerivedState({
    hasUnsavedChanges,
    loadRescueMessage,
    requestedMode: () => route.query.mode,
    requestedTarget: () => route.query.target,
    snapshotStore: configSnapshotStore,
    transitionIntent,
})
const { refreshWorkspaceFromSnapshot } = useControlCenterWorkspaceRefresh({
    fetchDefaultValues,
    loadRescueMessage,
    readRouteState: () => routeState.value,
    readViewState: () => viewState.value,
    router,
    snapshotStore: configSnapshotStore,
})
const {
    focusTarget,
    guideToTarget,
    handleModeSelect,
    navigateToControlCenter,
} = useControlCenterNavigation({
    announce,
    nextTick,
    readTargetElement: (target) => targetElements[target].value,
    routeState,
    router,
})
const {
    activationLoading,
    checkForExternalConfigChanges,
    handleActivateLiveTrading,
    handleDetectedExternalConfigChange,
    handleReloadAfterStalePrompt,
} = useControlCenterRuntimeActions({
    announce,
    apiUrl,
    hasUnsavedChanges,
    isDirty,
    navigateToControlCenter,
    normalizeBlockers: normalizeBackendBlockers,
    readiness,
    routeState,
    setTransitionIntent,
    snapshotStore: configSnapshotStore,
    syncControlCenterConfigChange,
})
const {
    activeSetupTarget,
    findSetupBlocker,
    getSetupTaskStatus,
    getSetupTaskSummary,
    handleMissionPrimaryAction,
    handleSetupEntryChoice,
    handleSetupEntryChoicePopState,
    handleSetupStyleChange,
    handleSetupTaskSelect,
    initializeSetupFlow,
    isSetupTaskExpanded,
    setupShowsAdvancedFields,
    setupStyle,
    setupTasks,
    showRestoreSetupFlow,
    showSetupEntryGate,
    showSetupStyleSelector,
    syncSetupChoiceForReadiness,
} = useControlCenterSetupFlow({
    focusTarget,
    guideToTarget,
    handleActivateLiveTrading,
    navigateToControlCenter,
    readiness,
    routeState,
    visibleBlockers,
})
const {
    advancedSections,
    dirtySummary,
    formattedTrustTimestamp,
    isStaleConfigTrustState,
    missionAlertTone,
    missionPrimaryLabel,
    missionSummaryTone,
    showMissionPanel,
    showModeStrip,
} = useControlCenterMissionState({
    changedSectionLabels,
    configTrustState,
    isDirty,
    readiness,
    routeState,
    showRestoreSetupFlow,
    showSetupEntryGate,
    transitionIntent,
    viewState,
})
const {
    handleBackupDownloadAction,
    handleMonitoringTestAction,
    handleRestoreBackupAction,
    handleSubmitWorkspace,
} = useControlCenterWorkspaceActions({
    announce,
    handleBackupDownload,
    handleRestoreBackup,
    navigateToControlCenter,
    normalizeBlockers: normalizeBackendBlockers,
    setTransitionIntent,
    submitForm,
    testMonitoringTelegram,
})

function isInteractiveTarget(target: EventTarget | null): boolean {
    return (
        target instanceof Element &&
        target.closest('button, a, input, select, textarea, label, [role="button"]') !==
            null
    )
}

async function handleSetupSectionShellClick(
    target: ControlCenterTarget,
    event: MouseEvent,
): Promise<void> {
    if (isSetupTaskExpanded(target) || isInteractiveTarget(event.target)) {
        return
    }
    await handleSetupTaskSelect(target)
}

watch(
    () => `${routeState.value.mode}:${routeState.value.target ?? ''}`,
    async () => {
        if (routeState.value.target) {
            await focusTarget(routeState.value.target)
        }
    },
    { flush: 'post' },
)

watch(
    () => readiness.value.firstRun,
    (firstRun) => {
        syncSetupChoiceForReadiness(firstRun)
    },
)

watch(
    () => configSnapshotStore.externalInvalidationToken.value,
    async (nextToken, previousToken) => {
        if (nextToken === 0 || nextToken === previousToken) {
            return
        }
        await handleDetectedExternalConfigChange(!document.hidden)
    },
)

onBeforeRouteLeave(() => confirmDiscardUnsavedChanges('route_leave'))

onMounted(async () => {
    initializeTimezoneOptions(getClientTimezone())
    initializeSetupFlow()
    window.addEventListener('beforeunload', handleBeforeUnload)
    window.addEventListener('keydown', handleGlobalKeydown)
    window.addEventListener('focus', checkForExternalConfigChanges)
    window.addEventListener('popstate', handleSetupEntryChoicePopState)
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
    window.removeEventListener('popstate', handleSetupEntryChoicePopState)
    disposeFeedback()
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

        <n-flex v-if="showMissionPanel" class="page-section" vertical>
            <n-card class="mission-panel" content-style="padding: 22px 24px;">
                <n-flex vertical :size="18">
                    <n-flex justify="space-between" align="center" :wrap="true">
                        <n-flex vertical :size="6">
                            <n-text depth="3" class="control-center-kicker">
                                Control Center
                            </n-text>
                            <div class="mission-heading-group">
                                <n-tag class="mission-status-tag" :type="missionSummaryTone">
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
                                strong
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
                        :type="missionAlertTone"
                        :title="dirtySummary"
                        role="status"
                        aria-live="polite"
                    >
                        <template v-if="transitionIntent">
                            {{ transitionIntent.message }}
                        </template>
                        <template v-else-if="configTrustState.kind === 'checking'">
                            {{ configTrustState.summary }}
                        </template>
                        <template v-else-if="isStaleConfigTrustState(configTrustState.kind)">
                            {{ configTrustState.summary }}
                            <span v-if="formattedTrustTimestamp">
                                Latest change detected at {{ formattedTrustTimestamp }}.
                            </span>
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
                        v-if="isStaleConfigTrustState(configTrustState.kind)"
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

        <n-flex v-if="showModeStrip" class="page-section" vertical>
            <n-card class="mode-strip-card" content-style="padding: 12px 14px;">
                <div class="mode-strip-shell">
                    <div class="mode-group">
                        <n-text depth="3" class="mode-group-label">Primary</n-text>
                        <n-flex class="mode-strip" :wrap="true" :size="[10, 10]">
                            <n-button
                                :type="routeState.mode === 'overview' ? 'primary' : 'default'"
                                :secondary="routeState.mode !== 'overview'"
                                :strong="routeState.mode === 'overview'"
                                @click="handleModeSelect('overview')"
                            >
                                Overview
                            </n-button>
                            <n-button
                                :type="routeState.mode === 'setup' ? 'primary' : 'default'"
                                :secondary="routeState.mode !== 'setup'"
                                :strong="routeState.mode === 'setup'"
                                @click="handleModeSelect('setup')"
                            >
                                Setup
                            </n-button>
                        </n-flex>
                    </div>

                    <div class="mode-group">
                        <n-text depth="3" class="mode-group-label">Expert and utility</n-text>
                        <n-flex class="mode-strip" :wrap="true" :size="[10, 10]">
                            <n-button
                                :type="routeState.mode === 'advanced' ? 'primary' : 'default'"
                                :secondary="routeState.mode !== 'advanced'"
                                :strong="routeState.mode === 'advanced'"
                                @click="handleModeSelect('advanced')"
                            >
                                Advanced
                            </n-button>
                            <n-button
                                :type="routeState.mode === 'utilities' ? 'primary' : 'default'"
                                :secondary="routeState.mode !== 'utilities'"
                                :strong="routeState.mode === 'utilities'"
                                @click="handleModeSelect('utilities')"
                            >
                                Utilities
                            </n-button>
                        </n-flex>
                    </div>
                </div>
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
                                                strong
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
                <n-card
                    v-if="showSetupEntryGate"
                    class="workspace-card setup-entry-card"
                    content-style="padding: 20px 22px;"
                >
                    <n-flex vertical :size="18">
                        <div class="setup-entry-intro">
                            <n-text depth="3" class="workspace-kicker">
                                Control Center
                            </n-text>
                            <h1 class="workspace-title">How do you want to begin?</h1>
                            <n-text depth="3" class="workspace-summary">
                                Start with your intent, not with a wall of options. Operators
                                migrating an existing instance should restore first. New
                                installations should begin with a safe dry-run setup.
                            </n-text>
                        </div>

                        <n-flex class="entry-choice-grid" :wrap="true" :size="[16, 16]">
                            <n-card size="small" class="entry-choice-card">
                                <n-flex vertical :size="12">
                                    <div>
                                        <h3 class="entry-choice-title">
                                            Restore existing installation
                                        </h3>
                                        <n-text depth="3">
                                            Import a config-only or full backup, then review
                                            readiness before anything goes live.
                                        </n-text>
                                    </div>
                                    <n-button
                                        type="primary"
                                        secondary
                                        @click="handleSetupEntryChoice('restore')"
                                    >
                                        Restore existing installation
                                    </n-button>
                                </n-flex>
                            </n-card>

                            <n-card size="small" class="entry-choice-card">
                                <n-flex vertical :size="12">
                                    <div>
                                        <h3 class="entry-choice-title">Start a new setup</h3>
                                        <n-text depth="3">
                                            Configure the essentials needed for a safe dry run
                                            before expert tuning or utilities appear.
                                        </n-text>
                                    </div>
                                    <n-button
                                        type="primary"
                                        @click="handleSetupEntryChoice('new')"
                                    >
                                        Start a new setup
                                    </n-button>
                                </n-flex>
                            </n-card>
                        </n-flex>
                    </n-flex>
                </n-card>

                <template v-else-if="showRestoreSetupFlow">
                    <n-card
                        class="workspace-card setup-flow-card"
                        content-style="padding: 20px 22px;"
                    >
                        <n-flex vertical :size="18">
                            <n-flex justify="space-between" align="center" :wrap="true">
                                <div>
                                    <h2 class="workspace-title">Restore and review</h2>
                                    <n-text depth="3" class="workspace-summary">
                                        Bring an existing Moonwalker installation forward first,
                                        then land in a readiness review before making changes.
                                    </n-text>
                                </div>
                                <n-button quaternary @click="handleSetupEntryChoice('new')">
                                    Start a new setup instead
                                </n-button>
                            </n-flex>

                            <n-alert type="info" title="Import first, review second">
                                Restoring does not skip safety review. Moonwalker will reload the
                                imported configuration and send you to a readiness check after the
                                backend completes the restore.
                            </n-alert>

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
                </template>

                <template v-else>
                    <n-card
                        v-if="showSetupStyleSelector"
                        class="workspace-card setup-style-card"
                        content-style="padding: 18px 20px;"
                    >
                        <n-flex vertical :size="12">
                            <n-flex justify="space-between" align="center" :wrap="true">
                                <div>
                                    <h2 class="workspace-title">Choose your setup pace</h2>
                                    <n-text depth="3" class="workspace-summary">
                                        Guided setup keeps the operator focused on the essentials.
                                        Full control reveals expert controls inline while you work.
                                    </n-text>
                                </div>
                                <n-button
                                    v-if="readiness.firstRun"
                                    class="setup-style-restore-action"
                                    type="warning"
                                    secondary
                                    @click="handleSetupEntryChoice('restore')"
                                >
                                    Restore instead
                                </n-button>
                            </n-flex>

                            <n-flex :wrap="true" :size="[10, 10]">
                                <n-button
                                    :type="setupStyle === 'guided' ? 'primary' : 'default'"
                                    secondary
                                    @click="handleSetupStyleChange('guided')"
                                >
                                    Guided setup
                                </n-button>
                                <n-button
                                    :type="setupStyle === 'full' ? 'primary' : 'default'"
                                    secondary
                                    @click="handleSetupStyleChange('full')"
                                >
                                    Full control
                                </n-button>
                            </n-flex>
                        </n-flex>
                    </n-card>

                    <div class="setup-progress-grid">
                        <button
                            v-for="task in setupTasks"
                            :key="task.target"
                            class="setup-progress-card"
                            :class="{
                                'setup-progress-card-active':
                                    activeSetupTarget === task.target,
                                'setup-progress-card-blocked': !!findSetupBlocker(task.target),
                                'setup-progress-card-ready':
                                    !findSetupBlocker(task.target) &&
                                    activeSetupTarget !== task.target,
                            }"
                            type="button"
                            @click="handleSetupTaskSelect(task.target)"
                        >
                            <span class="setup-progress-status">
                                {{ getSetupTaskStatus(task.target).label }}
                            </span>
                            <strong>{{ task.title }}</strong>
                            <span>{{ getSetupTaskSummary(task.target) }}</span>
                        </button>
                    </div>

                    <div
                        :ref="bindTargetElement('general')"
                        class="task-section task-section-shell"
                        :class="{ 'task-section-collapsed': !isSetupTaskExpanded('general') }"
                        id="control-center-general"
                        @click="handleSetupSectionShellClick('general', $event)"
                    >
                        <div class="task-section-heading-row">
                            <div
                                class="task-section-header"
                                tabindex="-1"
                                data-control-center-anchor
                            >
                                <h2>{{ getTaskPresentation('general').title }}</h2>
                                <n-text depth="3">{{ getTaskPresentation('general').summary }}</n-text>
                            </div>
                            <n-button
                                quaternary
                                @click="handleSetupTaskSelect('general')"
                            >
                                {{ isSetupTaskExpanded('general') ? 'Current step' : 'Open' }}
                            </n-button>
                        </div>
                        <div v-show="isSetupTaskExpanded('general')" class="task-section-body">
                            <ConfigGeneralSection
                                ref="generalFormRef"
                                :general="general"
                                :rules="rules"
                                :show-advanced-general="setupShowsAdvancedFields"
                                :show-advanced-toggle="false"
                                :show-debug="setupShowsAdvancedFields"
                                :timezone="timezone"
                            />
                        </div>
                    </div>

                    <div
                        :ref="bindTargetElement('exchange')"
                        class="task-section task-section-shell"
                        :class="{ 'task-section-collapsed': !isSetupTaskExpanded('exchange') }"
                        id="control-center-exchange"
                        @click="handleSetupSectionShellClick('exchange', $event)"
                    >
                        <div class="task-section-heading-row">
                            <div
                                class="task-section-header"
                                tabindex="-1"
                                data-control-center-anchor
                            >
                                <h2>{{ getTaskPresentation('exchange').title }}</h2>
                                <n-text depth="3">{{ getTaskPresentation('exchange').summary }}</n-text>
                            </div>
                            <n-button
                                quaternary
                                @click="handleSetupTaskSelect('exchange')"
                            >
                                {{ isSetupTaskExpanded('exchange') ? 'Current step' : 'Open' }}
                            </n-button>
                        </div>
                        <div v-show="isSetupTaskExpanded('exchange')" class="task-section-body">
                            <ConfigExchangeSection
                                ref="exchangeFormRef"
                                :currency="currency"
                                :exchange="exchange"
                                :exchanges="exchanges"
                                :market="market"
                                :rules="rules"
                                :show-advanced-general="setupShowsAdvancedFields"
                                :timerange="timerange"
                            />
                        </div>
                    </div>

                    <div
                        :ref="bindTargetElement('signal')"
                        class="task-section task-section-shell"
                        :class="{ 'task-section-collapsed': !isSetupTaskExpanded('signal') }"
                        id="control-center-signal"
                        @click="handleSetupSectionShellClick('signal', $event)"
                    >
                        <div class="task-section-heading-row">
                            <div
                                class="task-section-header"
                                tabindex="-1"
                                data-control-center-anchor
                            >
                                <h2>{{ getTaskPresentation('signal').title }}</h2>
                                <n-text depth="3">{{ getTaskPresentation('signal').summary }}</n-text>
                            </div>
                            <n-button
                                quaternary
                                @click="handleSetupTaskSelect('signal')"
                            >
                                {{ isSetupTaskExpanded('signal') ? 'Current step' : 'Open' }}
                            </n-button>
                        </div>
                        <div v-show="isSetupTaskExpanded('signal')" class="task-section-body">
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
                    </div>

                    <div
                        :ref="bindTargetElement('dca')"
                        class="task-section task-section-shell"
                        :class="{ 'task-section-collapsed': !isSetupTaskExpanded('dca') }"
                        id="control-center-dca"
                        @click="handleSetupSectionShellClick('dca', $event)"
                    >
                        <div class="task-section-heading-row">
                            <div
                                class="task-section-header"
                                tabindex="-1"
                                data-control-center-anchor
                            >
                                <h2>{{ getTaskPresentation('dca').title }}</h2>
                                <n-text depth="3">{{ getTaskPresentation('dca').summary }}</n-text>
                            </div>
                            <n-button
                                quaternary
                                @click="handleSetupTaskSelect('dca')"
                            >
                                {{ isSetupTaskExpanded('dca') ? 'Current step' : 'Open' }}
                            </n-button>
                        </div>
                        <div v-show="isSetupTaskExpanded('dca')" class="task-section-body">
                            <ConfigDcaSection
                                ref="dcaFormRef"
                                :dca="dca"
                                :rules="rules"
                                :sell-order-type-options="sellOrderTypeOptions"
                                :show-advanced-general="setupShowsAdvancedFields"
                                :strategy-options="signal.strategy_plugins"
                            />
                        </div>
                    </div>

                    <div
                        :ref="bindTargetElement('monitoring')"
                        class="task-section task-section-shell"
                        :class="{ 'task-section-collapsed': !isSetupTaskExpanded('monitoring') }"
                        id="control-center-monitoring"
                        @click="handleSetupSectionShellClick('monitoring', $event)"
                    >
                        <div class="task-section-heading-row">
                            <div
                                class="task-section-header"
                                tabindex="-1"
                                data-control-center-anchor
                            >
                                <h2>{{ getTaskPresentation('monitoring').title }}</h2>
                                <n-text depth="3">{{ getTaskPresentation('monitoring').summary }}</n-text>
                            </div>
                            <n-button
                                quaternary
                                @click="handleSetupTaskSelect('monitoring')"
                            >
                                {{ isSetupTaskExpanded('monitoring') ? 'Current step' : 'Open' }}
                            </n-button>
                        </div>
                        <div v-show="isSetupTaskExpanded('monitoring')" class="task-section-body">
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
                    </div>
                </template>
            </template>

            <template v-else-if="routeState.mode === 'advanced'">
                <div
                    v-for="section in advancedSections"
                    :id="section.sectionId"
                    :key="section.target"
                    :ref="bindTargetElement(section.target)"
                    class="task-section"
                >
                    <div class="task-section-header" tabindex="-1" data-control-center-anchor>
                        <h2>{{ section.title }}</h2>
                        <n-text depth="3">{{ section.summary }}</n-text>
                    </div>

                    <ConfigGeneralAdvancedSection
                        v-if="section.target === 'general'"
                        ref="generalFormRef"
                        :general="general"
                        :rules="rules"
                    />
                    <ConfigExchangeAdvancedSection
                        v-else-if="section.target === 'exchange'"
                        ref="exchangeFormRef"
                        :exchange="exchange"
                        :rules="rules"
                    />
                    <ConfigDcaAdvancedSection
                        v-else-if="section.target === 'dca'"
                        ref="dcaFormRef"
                        :dca="dca"
                        :rules="rules"
                    />
                    <ConfigFilterSection
                        v-else-if="section.target === 'filter'"
                        ref="filterFormRef"
                        :card-title="null"
                        :filter="filter"
                        :rules="rules"
                        :show-asap-fields="signal.signal === 'asap'"
                    />
                    <ConfigAutopilotSection
                        v-else-if="section.target === 'autopilot'"
                        ref="autopilotFormRef"
                        :autopilot="autopilot"
                        :card-title="null"
                        :rules="rules"
                        :show-fields="autopilot.enabled"
                    />
                    <ConfigIndicatorSection
                        v-else-if="section.target === 'indicator'"
                        :card-title="null"
                        ref="indicatorFormRef"
                        :history-lookback-options="historyLookbackOptions"
                        :indicator="indicator"
                        :rules="rules"
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
                                    class="utility-action-button"
                                    type="primary"
                                    strong
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
                                <n-button
                                    class="utility-action-button"
                                    secondary
                                    @click="openBackupFilePicker"
                                >
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
                                    class="utility-action-button"
                                    type="warning"
                                    :loading="restoreLoading"
                                    :disabled="!selectedBackupPayload"
                                    @click="handleRestoreBackupAction('config')"
                                >
                                    Restore config only
                                </n-button>
                                <n-button
                                    class="utility-action-button"
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
                                    class="utility-action-button"
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
                                            : 'Complete Telegram credentials in Setup first.'
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
    margin-bottom: 12px;
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
    color: var(--mw-color-text-muted);
    font-family: var(--mw-font-body);
    font-weight: 600;
}

.mission-panel {
    border: 1px solid rgba(29, 92, 73, 0.26);
    background: var(--mw-surface-mission);
    box-shadow: var(--mw-shadow-card);
    color: var(--mw-color-text-primary);
}

.mission-heading-group {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 10px;
}

.mission-heading-group :deep(.mission-status-tag) {
    border-radius: 999px;
    padding: 6px 12px;
}

.mission-heading-group :deep(.mission-status-tag .n-tag__content) {
    font-size: 0.95rem;
    font-weight: 600;
    line-height: 1;
}

.mission-title {
    font-family: var(--mw-font-display);
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

.mode-strip-shell {
    display: flex;
    flex-wrap: wrap;
    gap: 18px;
    justify-content: space-between;
}

.mode-group {
    display: flex;
    flex-direction: column;
    gap: 8px;
}

.mode-group-label {
    font-size: 0.78rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
}

.mode-strip {
    align-items: center;
}

.mode-strip :deep(.n-button--primary-type .n-button__content),
.mission-panel :deep(.n-button--primary-type .n-button__content),
.status-card :deep(.n-button--primary-type .n-button__content) {
    color: #f7f8f6;
    font-weight: 700;
    letter-spacing: 0.01em;
}

:deep(.utility-action-button:not(.n-button--disabled) .n-button__content) {
    font-weight: 700;
    letter-spacing: 0.01em;
}

:deep(.utility-action-button.n-button--primary-type.n-button--secondary:not(.n-button--disabled) .n-button__content),
:deep(.utility-action-button.n-button--primary-type.n-button--secondary:not(.n-button--disabled) .n-button__icon) {
    color: #18413a;
}

:deep(.utility-action-button.n-button--default-type.n-button--secondary:not(.n-button--disabled) .n-button__content) {
    color: var(--mw-color-text-primary);
}

.workspace-card,
.task-section {
    width: 100%;
}

.workspace-title {
    color: var(--mw-color-text-primary);
    font-family: var(--mw-font-display);
    font-size: clamp(1.35rem, 2.4vw, 1.8rem);
    line-height: 1.2;
    font-weight: 700;
    letter-spacing: -0.02em;
}

.workspace-summary {
    display: block;
    margin-top: 6px;
    max-width: 68ch;
}

.workspace-kicker {
    color: var(--mw-color-text-muted);
    display: inline-block;
    font-family: var(--mw-font-body);
    font-size: 0.82rem;
    font-weight: 600;
    letter-spacing: 0.12em;
    text-transform: uppercase;
}

.setup-entry-intro {
    display: flex;
    flex-direction: column;
    gap: 8px;
}

.setup-progress-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
    gap: 16px;
}

.setup-progress-card {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 6px;
    padding: 14px 16px;
    border: 1px solid rgba(29, 92, 73, 0.12);
    border-radius: 12px;
    background: var(--mw-surface-card-muted);
    color: inherit;
    text-align: left;
    cursor: pointer;
    transition:
        border-color 120ms ease,
        box-shadow 120ms ease,
        transform 120ms ease;
}

.setup-progress-card:hover {
    border-color: rgba(29, 92, 73, 0.28);
    box-shadow: 0 8px 18px rgba(24, 33, 29, 0.06);
    transform: translateY(-1px);
}

.setup-progress-card strong {
    color: var(--mw-color-text-primary);
    font-family: var(--mw-font-display);
    font-size: 0.96rem;
}

.setup-progress-card span:last-child {
    font-size: 0.88rem;
    color: var(--mw-color-text-secondary);
}

.setup-progress-status {
    font-size: 0.72rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: rgba(29, 92, 73, 0.78);
    font-family: var(--mw-font-mono);
}

.setup-progress-card-active {
    border-color: rgba(29, 92, 73, 0.35);
    background: var(--mw-surface-card-success);
}

.setup-progress-card-blocked {
    border-color: rgba(183, 121, 31, 0.26);
    background: var(--mw-surface-card-warning);
}

.setup-progress-card-ready {
    border-color: rgba(46, 125, 91, 0.2);
}

.task-section {
    display: flex;
    flex-direction: column;
    gap: 10px;
}

.task-section-shell {
    border: 1px solid rgba(29, 92, 73, 0.12);
    border-radius: var(--mw-radius-lg);
    padding: 16px 18px;
    background: var(--mw-surface-card);
}

.task-section-collapsed {
    background: var(--mw-surface-card-subtle);
    cursor: pointer;
}

.task-section-heading-row {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 12px;
}

.task-section-body {
    margin-top: 6px;
}

.entry-choice-grid {
    align-items: stretch;
}

.entry-choice-card {
    min-width: min(320px, 100%);
    flex: 1 1 320px;
    border: 1px solid rgba(29, 92, 73, 0.16);
    background: var(--mw-surface-card);
    box-shadow: var(--mw-shadow-card);
}

.entry-choice-title {
    color: var(--mw-color-text-primary);
    font-family: var(--mw-font-display);
    font-size: 1.12rem;
    font-weight: 700;
    letter-spacing: -0.01em;
}

.setup-entry-card,
.setup-flow-card,
.setup-style-card {
    border: 1px solid rgba(29, 92, 73, 0.14);
    background: var(--mw-surface-shell);
}

.setup-style-restore-action {
    font-weight: 600;
}

.task-section-header {
    display: flex;
    flex-direction: column;
    gap: 4px;
}

.task-section-header:focus,
.task-section-header:focus-visible {
    outline: none;
    box-shadow: none;
}

.task-section-header h2,
.status-card-title {
    color: var(--mw-color-text-primary);
    font-family: var(--mw-font-display);
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

    .mode-strip-shell {
        gap: 12px;
    }

    .setup-progress-grid {
        grid-template-columns: 1fr;
    }

    .task-section-heading-row {
        flex-direction: column;
    }

    .mission-panel :deep(.n-alert) {
        padding-right: 0;
    }
}
</style>
