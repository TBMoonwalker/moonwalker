<script setup lang="ts">
import { nextTick, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useMessage } from 'naive-ui/es/message'

import ControlCenterMissionPanel from '../components/control-center/ControlCenterMissionPanel.vue'
import ControlCenterAdvancedWorkspace from '../components/control-center/ControlCenterAdvancedWorkspace.vue'
import ControlCenterModeStrip from '../components/control-center/ControlCenterModeStrip.vue'
import ControlCenterOverviewWorkspace from '../components/control-center/ControlCenterOverviewWorkspace.vue'
import ControlCenterSetupWorkspace from '../components/control-center/ControlCenterSetupWorkspace.vue'
import ControlCenterUtilitiesWorkspace from '../components/control-center/ControlCenterUtilitiesWorkspace.vue'
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
import { normalizeControlCenterBlockers } from '../control-center/blockers'
import { createControlCenterConfigChangeSynchronizer } from '../control-center/configChangeSync'
import { useSharedConfigSnapshot } from '../control-center/configSnapshotStore'
import { getTaskPresentation } from '../control-center/taskRegistry'
import type { ControlCenterTarget } from '../control-center/types'
import { useConfigAdvancedGeneral } from '../composables/useConfigAdvancedGeneral'
import { useConfigBackupRestore } from '../composables/useConfigBackupRestore'
import { useConfigLoadFlow } from '../composables/useConfigLoadFlow'
import { useConfigMonitoringTest } from '../composables/useConfigMonitoringTest'
import { useConfigPageState } from '../composables/useConfigPageState'
import { useConfigPersistableState } from '../composables/useConfigPersistableState'
import { useControlCenterDerivedState } from '../composables/useControlCenterDerivedState'
import { useControlCenterFeedback } from '../composables/useControlCenterFeedback'
import { useControlCenterLifecycle } from '../composables/useControlCenterLifecycle'
import { useControlCenterMissionState } from '../composables/useControlCenterMissionState'
import { useControlCenterNavigation } from '../composables/useControlCenterNavigation'
import { useControlCenterRuntimeActions } from '../composables/useControlCenterRuntimeActions'
import { useControlCenterSetupShellInteractions } from '../composables/useControlCenterSetupShellInteractions'
import { useControlCenterSetupFlow } from '../composables/useControlCenterSetupFlow'
import { useControlCenterTargetRegistry } from '../composables/useControlCenterTargetRegistry'
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

const route = useRoute()
const router = useRouter()
const message = useMessage()
const configSnapshotStore = useSharedConfigSnapshot()

const apiUrl = (path: string): string => new URL(path, MOONWALKER_API_ORIGIN).toString()
const isLoading = ref(true)
const showAdvancedGeneral = ref(false)
const loadRescueMessage = ref<string | null>(null)

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

const { bindTargetElement, readTargetElement } =
    useControlCenterTargetRegistry()

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

function bindBackupFileInput(element: Element | null): void {
    backupFileInputRef.value =
        element instanceof HTMLInputElement ? element : null
}

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
    readTargetElement,
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
    normalizeBlockers: normalizeControlCenterBlockers,
    readiness,
    routeState,
    setTransitionIntent,
    snapshotStore: configSnapshotStore,
    syncControlCenterConfigChange,
})
const {
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
    normalizeBlockers: normalizeControlCenterBlockers,
    setTransitionIntent,
    submitForm,
    testMonitoringTelegram,
})
const { handleSetupSectionShellClick } =
    useControlCenterSetupShellInteractions({
        handleSetupTaskSelect,
        isSetupTaskExpanded,
    })

useControlCenterLifecycle({
    checkForExternalConfigChanges,
    confirmDiscardUnsavedChanges,
    disposeFeedback,
    focusTarget,
    getClientTimezone,
    handleBeforeUnload: handleBeforeUnload as EventListener,
    handleDetectedExternalConfigChange,
    handleGlobalKeydown: handleGlobalKeydown as EventListener,
    handleSetupEntryChoicePopState:
        handleSetupEntryChoicePopState as EventListener,
    initializeSetupFlow,
    initializeTimezoneOptions,
    readiness,
    refreshWorkspaceFromSnapshot,
    routeState,
    snapshotStore: configSnapshotStore,
    staleCheckIntervalMs: STALE_CHECK_INTERVAL_MS,
    syncSetupChoiceForReadiness,
})
</script>

<template>
    <div class="page-shell control-center-page">
        <div class="sr-only" aria-live="polite" aria-atomic="true">
            {{ liveRegionMessage }}
        </div>

        <n-flex v-if="showMissionPanel" class="page-section" vertical>
            <ControlCenterMissionPanel
                :activation-loading="activationLoading"
                :config-trust-state="configTrustState"
                :dirty-summary="dirtySummary"
                :formatted-trust-timestamp="formattedTrustTimestamp"
                :is-dirty="isDirty"
                :is-stale-config-trust-state="isStaleConfigTrustState"
                :is-submit-disabled="isSubmitDisabled"
                :mission-alert-tone="missionAlertTone"
                :mission-primary-label="missionPrimaryLabel"
                :mission-summary-tone="missionSummaryTone"
                :readiness="readiness"
                :save-state="saveState"
                :transition-intent="transitionIntent"
                :view-state="viewState"
                @mission-primary="handleMissionPrimaryAction"
                @reload-latest="handleReloadAfterStalePrompt"
                @save="handleSubmitWorkspace"
            />
        </n-flex>

        <n-flex v-if="showModeStrip" class="page-section" vertical>
            <ControlCenterModeStrip
                :route-mode="routeState.mode"
                @select-mode="handleModeSelect"
            />
        </n-flex>

        <n-flex class="page-section workspace-section" vertical>
            <template v-if="routeState.mode === 'overview'">
                <ControlCenterOverviewWorkspace
                    :activation-loading="activationLoading"
                    :exchange-currency="exchange.currency"
                    :exchange-name="exchange.name"
                    :live-activation-ref="bindTargetElement('live-activation')"
                    :readiness="readiness"
                    :signal-source="signal.signal"
                    :visible-blockers="visibleBlockers"
                    @activate-live="handleActivateLiveTrading"
                    @select-target="guideToTarget"
                />
            </template>

            <template v-else-if="routeState.mode === 'setup'">
                <ControlCenterSetupWorkspace
                    :bind-backup-file-input="bindBackupFileInput"
                    :bind-target-element="bindTargetElement"
                    :get-setup-task-status="getSetupTaskStatus"
                    :get-setup-task-summary="getSetupTaskSummary"
                    :has-selected-backup-payload="!!selectedBackupPayload"
                    :is-setup-task-expanded="isSetupTaskExpanded"
                    :readiness-first-run="readiness.firstRun"
                    :restore-loading="restoreLoading"
                    :selected-backup-config-count="selectedBackupConfigCount"
                    :selected-backup-file-name="selectedBackupFileName"
                    :selected-backup-has-trade-data="selectedBackupHasTradeData"
                    :setup-style="setupStyle"
                    :setup-tasks="setupTasks"
                    :show-restore-setup-flow="showRestoreSetupFlow"
                    :show-setup-entry-gate="showSetupEntryGate"
                    :show-setup-style-selector="showSetupStyleSelector"
                    @backup-file-selected="handleBackupFileSelected"
                    @clear-selected-backup="clearSelectedBackup"
                    @open-backup-file-picker="openBackupFilePicker"
                    @restore-backup="handleRestoreBackupAction"
                    @select-entry-choice="handleSetupEntryChoice"
                    @select-setup-style="handleSetupStyleChange"
                    @select-setup-target="handleSetupTaskSelect"
                    @setup-shell-click="handleSetupSectionShellClick"
                >
                    <template #general>
                        <ConfigGeneralSection
                            ref="generalFormRef"
                            :general="general"
                            :rules="rules"
                            :show-advanced-general="setupShowsAdvancedFields"
                            :show-advanced-toggle="false"
                            :show-debug="setupShowsAdvancedFields"
                            :timezone="timezone"
                        />
                    </template>

                    <template #exchange>
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
                    </template>

                    <template #signal>
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
                    </template>

                    <template #dca>
                        <ConfigDcaSection
                            ref="dcaFormRef"
                            :dca="dca"
                            :rules="rules"
                            :sell-order-type-options="sellOrderTypeOptions"
                            :show-advanced-general="setupShowsAdvancedFields"
                            :strategy-options="signal.strategy_plugins"
                        />
                    </template>

                    <template #monitoring>
                        <ConfigMonitoringSection
                            ref="monitoringFormRef"
                            :can-test="canTestMonitoringTelegram()"
                            :monitoring="monitoring"
                            :on-test="handleMonitoringTestAction"
                            :rules="rules"
                            :show-test-action="false"
                            :test-loading="monitoringTestLoading"
                        />
                    </template>
                </ControlCenterSetupWorkspace>
            </template>

            <template v-else-if="routeState.mode === 'advanced'">
                <ControlCenterAdvancedWorkspace
                    :advanced-sections="advancedSections"
                    :bind-target-element="bindTargetElement"
                >
                    <template #general>
                        <ConfigGeneralAdvancedSection
                            ref="generalFormRef"
                            :general="general"
                            :rules="rules"
                        />
                    </template>

                    <template #exchange>
                        <ConfigExchangeAdvancedSection
                            ref="exchangeFormRef"
                            :exchange="exchange"
                            :rules="rules"
                        />
                    </template>

                    <template #dca>
                        <ConfigDcaAdvancedSection
                            ref="dcaFormRef"
                            :dca="dca"
                            :rules="rules"
                        />
                    </template>

                    <template #filter>
                        <ConfigFilterSection
                            ref="filterFormRef"
                            :card-title="null"
                            :filter="filter"
                            :rules="rules"
                            :show-asap-fields="signal.signal === 'asap'"
                        />
                    </template>

                    <template #autopilot>
                        <ConfigAutopilotSection
                            ref="autopilotFormRef"
                            :autopilot="autopilot"
                            :card-title="null"
                            :rules="rules"
                            :show-fields="autopilot.enabled"
                        />
                    </template>

                    <template #indicator>
                        <ConfigIndicatorSection
                            ref="indicatorFormRef"
                            :card-title="null"
                            :history-lookback-options="historyLookbackOptions"
                            :indicator="indicator"
                            :rules="rules"
                        />
                    </template>
                </ControlCenterAdvancedWorkspace>
            </template>

            <template v-else>
                <ControlCenterUtilitiesWorkspace
                    :backup-download-loading="backupDownloadLoading"
                    :backup-include-trade-data="backupIncludeTradeData"
                    :backup-restore-summary="getTaskPresentation('backup-restore').summary"
                    :backup-restore-title="getTaskPresentation('backup-restore').title"
                    :bind-backup-file-input="bindBackupFileInput"
                    :bind-backup-restore-target-ref="bindTargetElement('backup-restore')"
                    :can-test-monitoring-telegram="canTestMonitoringTelegram()"
                    :has-selected-backup-payload="!!selectedBackupPayload"
                    :monitoring-test-loading="monitoringTestLoading"
                    :restore-loading="restoreLoading"
                    :selected-backup-config-count="selectedBackupConfigCount"
                    :selected-backup-file-name="selectedBackupFileName"
                    :selected-backup-has-trade-data="selectedBackupHasTradeData"
                    @backup-file-selected="handleBackupFileSelected"
                    @clear-selected-backup="clearSelectedBackup"
                    @download-backup="handleBackupDownloadAction"
                    @monitoring-test="handleMonitoringTestAction"
                    @open-backup-file-picker="openBackupFilePicker"
                    @restore-backup="handleRestoreBackupAction"
                    @update:backup-include-trade-data="backupIncludeTradeData = $event"
                />
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
}
</style>
