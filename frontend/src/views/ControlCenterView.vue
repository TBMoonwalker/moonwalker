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
import { normalizeControlCenterBlockers } from '../control-center/blockers'
import { createControlCenterConfigChangeSynchronizer } from '../control-center/configChangeSync'
import { useSharedConfigSnapshot } from '../control-center/configSnapshotStore'
import { getTaskPresentation } from '../control-center/taskRegistry'
import type { ControlCenterTarget } from '../control-center/types'
import { useConfigEditorAssembly } from '../composables/useConfigEditorAssembly'
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
import { buildMoonwalkerApiUrl } from '../helpers/configEditorDefaults'

const route = useRoute()
const router = useRouter()
const message = useMessage()
const configSnapshotStore = useSharedConfigSnapshot()

const loadRescueMessage = ref<string | null>(null)

const STALE_CHECK_INTERVAL_MS = 15000

const { bindTargetElement, readTargetElement } =
    useControlCenterTargetRegistry()

const {
    autopilot,
    autopilotFormRef,
    backupDownloadLoading,
    backupIncludeTradeData,
    bindBackupFileInput,
    canTestMonitoringTelegram,
    changedSectionLabels,
    clearSelectedBackup,
    confirmDiscardUnsavedChanges,
    currency,
    dca,
    dcaFormRef,
    exchange,
    exchangeFormRef,
    exchanges,
    fetchAsapSymbolsForCurrency,
    fetchDefaultValues,
    filter,
    filterFormRef,
    general,
    generalFormRef,
    getAsapMissingFieldsLabel,
    handleAsapUrlInput,
    handleBackupDownload,
    handleBackupFileSelected,
    handleBeforeUnload,
    handleCsvSignalFileSelected,
    handleGlobalKeydown,
    handleRestoreBackup,
    handleSignalSettingsSelect,
    historyLookbackOptions,
    indicator,
    indicatorFormRef,
    initializeClientTimezoneOptions,
    isAsapExchangeReady,
    isDirty,
    isLoading,
    isSubmitDisabled,
    hasUnsavedChanges,
    market,
    monitoring,
    monitoringFormRef,
    monitoringTestLoading,
    openBackupFilePicker,
    restoreLoading,
    rules,
    saveState,
    sellOrderTypeOptions,
    selectedBackupConfigCount,
    selectedBackupFileName,
    selectedBackupHasTradeData,
    selectedBackupPayload,
    showAdvancedGeneral,
    signal,
    signalFormRef,
    submitForm,
    symsignals,
    testMonitoringTelegram,
    timerange,
    timezone,
} = useConfigEditorAssembly({
    backupRestore: {
        reloadConfig: async () => {
            const result = await syncControlCenterConfigChange('restore')
            if (result.status === 'error') {
                throw new Error(result.message)
            }
        },
    },
    load: {
        loadConfig: async () => {
            const loadedConfig = await configSnapshotStore.ensureLoaded(false)
            return loadedConfig ?? configSnapshotStore.snapshot.value
        },
    },
    message,
    readSubmitShowAdvancedGeneral: () =>
        routeState.value.mode === 'advanced' || setupShowsAdvancedFields.value,
    save: {
        onSaved: async () => {
            const result = await syncControlCenterConfigChange('save')
            if (result.status === 'error') {
                throw new Error(result.message)
            }
        },
    },
    surfaceMessages: {
        backupRestore: false,
        load: false,
        monitoring: false,
        save: false,
    },
    validation: {
        onInvalid: async (sectionKey) => {
            const invalidTarget = sectionKey as ControlCenterTarget
            if (invalidTarget) {
                await guideToTarget(invalidTarget)
            }
        },
        onSubmitShortcut: handleSubmitWorkspace,
        onValidSubmit: handleSubmitWorkspace,
    },
})

const syncControlCenterConfigChange =
    createControlCenterConfigChangeSynchronizer({
    emitInvalidation: (origin) => {
        configSnapshotStore.emitLocalInvalidation(origin)
    },
    refreshWorkspace: (force) => refreshWorkspaceFromSnapshot(force),
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
    apiUrl: buildMoonwalkerApiUrl,
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
    handleBeforeUnload: handleBeforeUnload as EventListener,
    handleDetectedExternalConfigChange,
    handleGlobalKeydown: handleGlobalKeydown as EventListener,
    handleSetupEntryChoicePopState:
        handleSetupEntryChoicePopState as EventListener,
    initializeClientTimezoneOptions,
    initializeSetupFlow,
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
