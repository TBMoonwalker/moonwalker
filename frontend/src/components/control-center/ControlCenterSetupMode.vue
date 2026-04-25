<script setup lang="ts">
import type { FormRules } from 'naive-ui/es/form'
import type { VNodeRef } from 'vue'

import type { SetupEntryChoice } from '../../control-center/setupEntryHistory'
import type {
    CapitalModel,
    DcaModel,
    ExchangeModel,
    GeneralModel,
    MixedSelectOption,
    MonitoringModel,
    SignalEditorModel,
    StringSelectOption,
} from '../../config-editor/types'
import type {
    ControlCenterTarget,
    ControlCenterTaskPresentation,
} from '../../control-center/types'
import type { SetupStyle } from '../../composables/useControlCenterSetupFlow'
import ControlCenterSetupWorkspace from './ControlCenterSetupWorkspace.vue'
import ConfigCapitalSection from '../config/ConfigCapitalSection.vue'
import ConfigDcaSection from '../config/ConfigDcaSection.vue'
import ConfigExchangeSection from '../config/ConfigExchangeSection.vue'
import ConfigGeneralSection from '../config/ConfigGeneralSection.vue'
import ConfigMonitoringSection from '../config/ConfigMonitoringSection.vue'
import ConfigSignalSection from '../config/ConfigSignalSection.vue'

type BackupRestoreMode = 'config' | 'full'
interface SetupTaskStatus {
    label: string
    type: 'default' | 'info' | 'warning' | 'success'
}

defineProps<{
    bindBackupFileInput: (element: Element | null) => void
    bindTargetElement: (
        target: ControlCenterTarget,
    ) => (element: Element | null) => void
    canTestMonitoringTelegram: boolean
    capital: CapitalModel
    capitalFormRef?: VNodeRef
    currency: StringSelectOption[]
    dca: DcaModel
    dcaFormRef?: VNodeRef
    exchange: ExchangeModel
    exchangeFormRef?: VNodeRef
    exchanges: StringSelectOption[]
    fetchAsapSymbolsForCurrency: () => void | Promise<void>
    general: GeneralModel
    generalFormRef?: VNodeRef
    getAsapMissingFieldsLabel: () => string
    getSetupTaskStatus: (target: ControlCenterTarget) => SetupTaskStatus
    getSetupTaskSummary: (target: ControlCenterTarget) => string
    handleAsapUrlInput: (value: string) => void
    handleCsvSignalFileSelected: (event: Event) => void | Promise<void>
    handleMonitoringTestAction: () => void | Promise<void>
    handleSignalSettingsSelect: () => void
    hasSelectedBackupPayload: boolean
    isAsapExchangeReady: boolean
    isSetupTaskExpanded: (target: ControlCenterTarget) => boolean
    market: StringSelectOption[]
    monitoring: MonitoringModel
    monitoringFormRef?: VNodeRef
    monitoringTestLoading: boolean
    readinessFirstRun: boolean
    restoreLoading: boolean
    rules: FormRules
    selectedBackupConfigCount: number
    selectedBackupFileName: string | null
    selectedBackupHasTradeData: boolean
    sellOrderTypeOptions: StringSelectOption[]
    setupStyle: SetupStyle
    setupShowsAdvancedFields: boolean
    setupTasks: ControlCenterTaskPresentation[]
    showRestoreSetupFlow: boolean
    showSetupEntryGate: boolean
    showSetupStyleSelector: boolean
    signal: SignalEditorModel
    signalFormRef?: VNodeRef
    symsignals: MixedSelectOption[]
    timerange: StringSelectOption[]
    timezone: StringSelectOption[]
}>()

const emit = defineEmits<{
    'backup-file-selected': [event: Event]
    'clear-selected-backup': []
    'open-backup-file-picker': []
    'restore-backup': [mode: BackupRestoreMode]
    'select-entry-choice': [choice: SetupEntryChoice]
    'select-setup-style': [style: SetupStyle]
    'select-setup-target': [target: ControlCenterTarget]
    'setup-shell-click': [target: ControlCenterTarget, event: MouseEvent]
}>()
</script>

<template>
    <ControlCenterSetupWorkspace
        :bind-backup-file-input="bindBackupFileInput"
        :bind-target-element="bindTargetElement"
        :get-setup-task-status="getSetupTaskStatus"
        :get-setup-task-summary="getSetupTaskSummary"
        :has-selected-backup-payload="hasSelectedBackupPayload"
        :is-setup-task-expanded="isSetupTaskExpanded"
        :readiness-first-run="readinessFirstRun"
        :restore-loading="restoreLoading"
        :selected-backup-config-count="selectedBackupConfigCount"
        :selected-backup-file-name="selectedBackupFileName"
        :selected-backup-has-trade-data="selectedBackupHasTradeData"
        :setup-style="setupStyle"
        :setup-tasks="setupTasks"
        :show-restore-setup-flow="showRestoreSetupFlow"
        :show-setup-entry-gate="showSetupEntryGate"
        :show-setup-style-selector="showSetupStyleSelector"
        @backup-file-selected="emit('backup-file-selected', $event)"
        @clear-selected-backup="emit('clear-selected-backup')"
        @open-backup-file-picker="emit('open-backup-file-picker')"
        @restore-backup="emit('restore-backup', $event)"
        @select-entry-choice="emit('select-entry-choice', $event)"
        @select-setup-style="emit('select-setup-style', $event)"
        @select-setup-target="emit('select-setup-target', $event)"
        @setup-shell-click="(target, event) => emit('setup-shell-click', target, event)"
    >
        <template #general>
            <ConfigGeneralSection
                :ref="generalFormRef"
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
                :ref="exchangeFormRef"
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
                :ref="signalFormRef"
                :asap-missing-fields-label="getAsapMissingFieldsLabel()"
                :is-asap-exchange-ready="isAsapExchangeReady"
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
                :ref="dcaFormRef"
                :dca="dca"
                :rules="rules"
                :sell-order-type-options="sellOrderTypeOptions"
                :show-advanced-general="setupShowsAdvancedFields"
                :strategy-options="signal.strategy_plugins"
            />
        </template>

        <template #capital>
            <ConfigCapitalSection
                :ref="capitalFormRef"
                :capital="capital"
                :rules="rules"
            />
        </template>

        <template #monitoring>
            <ConfigMonitoringSection
                :ref="monitoringFormRef"
                :can-test="canTestMonitoringTelegram"
                :monitoring="monitoring"
                :on-test="handleMonitoringTestAction"
                :rules="rules"
                :show-test-action="false"
                :test-loading="monitoringTestLoading"
            />
        </template>
    </ControlCenterSetupWorkspace>
</template>
