<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useMessage } from 'naive-ui/es/message'

import ControlCenterAdvancedMode from '../components/control-center/ControlCenterAdvancedMode.vue'
import ControlCenterMissionPanel from '../components/control-center/ControlCenterMissionPanel.vue'
import ControlCenterModeStrip from '../components/control-center/ControlCenterModeStrip.vue'
import ControlCenterSetupMode from '../components/control-center/ControlCenterSetupMode.vue'
import ControlCenterUtilitiesWorkspace from '../components/control-center/ControlCenterUtilitiesWorkspace.vue'
import StrategyBuilderWorkspace from '../components/control-center/StrategyBuilderWorkspace.vue'
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
const pageHeading = computed(() => {
    if (routeState.value.mode === 'strategy-builder') {
        return {
            title: 'Strategy Builder',
            description: 'Build and validate trading strategies.',
        }
    }
    if (routeState.value.mode === 'utilities') {
        return {
            title: 'Utilities',
            description: 'Back up Moonwalker and check saved connections.',
        }
    }
    return {
        title: 'Configuration',
        description: 'Set up Moonwalker and adjust its trading behavior.',
    }
})
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
    capital,
    capitalFormRef,
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
    baselineState,
    isDirty,
    isSubmitDisabled,
    hasUnsavedChanges,
    market,
    monitoring,
    monitoringFormRef,
    monitoringTestLoading,
    openBackupFilePicker,
    restoreLoading,
    restoreReview,
    rules,
    saveState,
    sellOrderTypeOptions,
    selectedBackupConfigCount,
    selectedBackupFileName,
    selectedBackupHasTradeData,
    selectedBackupPayload,
    signal,
    signalFormRef,
    submitForm,
    symsignals,
    testMonitoringTelegram,
    timerange,
    tradeModeSwitchGuard,
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
        onSubmitShortcut: async () => {
            await handleSubmitWorkspace()
        },
        onValidSubmit: async () => {
            await handleSubmitWorkspace()
        },
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
const tradingPaused = computed(() => configSnapshotStore.snapshot.value?.trading_paused === true)
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
    isTradingPaused: tradingPaused,
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
    <div class="page-shell control-center-page operator-console-page">
        <div class="sr-only" aria-live="polite" aria-atomic="true">
            {{ liveRegionMessage }}
        </div>

        <header class="operator-page-heading">
            <h1>{{ pageHeading.title }}</h1>
            <p>{{ pageHeading.description }}</p>
        </header>

        <n-alert
            v-if="showMissionPanel && viewState.kind === 'rescue'"
            class="config-recovery-alert"
            type="warning"
            title="Configuration unavailable"
        >
            <div class="recovery-content">
                <span>{{ viewState.summary }}</span>
                <n-button secondary type="warning" @click="refreshWorkspaceFromSnapshot(true)">
                    Retry config load
                </n-button>
            </div>
        </n-alert>

        <n-flex v-else-if="showMissionPanel" class="page-section" vertical>
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

        <n-flex id="cc-workspace-panel" :role="showModeStrip ? 'tabpanel' : undefined" :aria-labelledby="showModeStrip ? 'cc-mode-tab-' + routeState.mode : undefined" class="page-section workspace-section" vertical>
            <template v-if="routeState.mode === 'setup'">
                <ControlCenterSetupMode
                    :activation-disabled="isDirty || configTrustState.kind !== 'trusted'"
                    :activation-loading="activationLoading"
                    :bind-backup-file-input="bindBackupFileInput"
                    :bind-target-element="bindTargetElement"
                    :capital="capital"
                    :capital-form-ref="capitalFormRef"
                    :can-test-monitoring-telegram="canTestMonitoringTelegram()"
                    :currency="currency"
                    :dca="dca"
                    :dca-form-ref="dcaFormRef"
                    :dry-run-activation-locked="
                        baselineState?.exchange?.dry_run === true
                    "
                    :exchange="exchange"
                    :exchange-form-ref="exchangeFormRef"
                    :exchanges="exchanges"
                    :fetch-asap-symbols-for-currency="fetchAsapSymbolsForCurrency"
                    :general="general"
                    :general-form-ref="generalFormRef"
                    :get-asap-missing-fields-label="getAsapMissingFieldsLabel"
                    :get-setup-task-status="getSetupTaskStatus"
                    :get-setup-task-summary="getSetupTaskSummary"
                    :handle-asap-url-input="handleAsapUrlInput"
                    :handle-csv-signal-file-selected="handleCsvSignalFileSelected"
                    :handle-monitoring-test-action="handleMonitoringTestAction"
                    :handle-signal-settings-select="handleSignalSettingsSelect"
                    :has-selected-backup-payload="!!selectedBackupPayload"
                    :is-asap-exchange-ready="isAsapExchangeReady()"
                    :is-setup-task-expanded="isSetupTaskExpanded"
                    :live-activation-available="readiness.complete && readiness.dryRun"
                    :market="market"
                    :monitoring="monitoring"
                    :monitoring-form-ref="monitoringFormRef"
                    :monitoring-test-loading="monitoringTestLoading"
                    :readiness-complete="readiness.complete"
                    :readiness-first-run="readiness.firstRun"
                    :restore-loading="restoreLoading"
                    :restore-review="restoreReview"
                    :rules="rules"
                    :selected-backup-config-count="selectedBackupConfigCount"
                    :selected-backup-file-name="selectedBackupFileName"
                    :selected-backup-has-trade-data="selectedBackupHasTradeData"
                    :sell-order-type-options="sellOrderTypeOptions"
                    :setup-style="setupStyle"
                    :setup-shows-advanced-fields="setupShowsAdvancedFields"
                    :setup-tasks="setupTasks"
                    :show-restore-setup-flow="showRestoreSetupFlow"
                    :show-setup-entry-gate="showSetupEntryGate"
                    :show-setup-style-selector="showSetupStyleSelector"
                    :signal="signal"
                    :signal-form-ref="signalFormRef"
                    :symsignals="symsignals"
                    :timerange="timerange"
                    :trade-mode-switch-guard="tradeModeSwitchGuard"
                    :timezone="timezone"
                    @activate-live="handleActivateLiveTrading"
                    @backup-file-selected="handleBackupFileSelected"
                    @clear-selected-backup="clearSelectedBackup"
                    @open-backup-file-picker="openBackupFilePicker"
                    @restore-backup="handleRestoreBackupAction"
                    @select-entry-choice="handleSetupEntryChoice"
                    @select-setup-style="handleSetupStyleChange"
                    @select-setup-target="handleSetupTaskSelect"
                    @setup-shell-click="handleSetupSectionShellClick"
                />
            </template>

            <template v-else-if="routeState.mode === 'advanced'">
                <ControlCenterAdvancedMode
                    :advanced-sections="advancedSections"
                    :autopilot="autopilot"
                    :autopilot-form-ref="autopilotFormRef"
                    :bind-target-element="bindTargetElement"
                    :capital="capital"
                    :capital-form-ref="capitalFormRef"
                    :dca="dca"
                    :dca-form-ref="dcaFormRef"
                    :exchange="exchange"
                    :exchange-form-ref="exchangeFormRef"
                    :filter="filter"
                    :filter-form-ref="filterFormRef"
                    :general="general"
                    :general-form-ref="generalFormRef"
                    :history-lookback-options="historyLookbackOptions"
                    :indicator="indicator"
                    :indicator-form-ref="indicatorFormRef"
                    :rules="rules"
                    :signal="signal"
                />
            </template>

            <template v-else-if="routeState.mode === 'strategy-builder'">
                <StrategyBuilderWorkspace />
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
                    :restore-review="restoreReview"
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
    gap: 12px;
}

.page-section {
    min-width: 0;
}

.page-section:last-child {
    margin-bottom: 0;
}

.workspace-section {
    gap: 12px;
}

.recovery-content {
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 12px;
}

.config-recovery-alert :deep(.n-alert-body__content) {
    width: 100%;
}

:deep(.utility-action-button:not(.n-button--disabled) .n-button__content) {
    font-weight: 500;
    letter-spacing: 0.01em;
}

:deep(.utility-action-button.n-button--primary-type.n-button--secondary:not(.n-button--disabled) .n-button__content),
:deep(.utility-action-button.n-button--primary-type.n-button--secondary:not(.n-button--disabled) .n-button__icon) {
    color: var(--mw-color-primary-strong);
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

@media (max-width: 767px) {
    .page-section {
        min-width: 0;
    }

    .control-center-page :deep(.n-button),
    .control-center-page :deep(.n-pagination-item),
    .control-center-page :deep(.n-base-btn) {
        min-height: 44px !important;
    }
}

</style>
