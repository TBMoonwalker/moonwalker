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
import type { TradeModeSwitchGuardState } from '../../helpers/configLoad'
import type { RestoreReviewState } from '../../composables/useConfigBackupRestore'
import type {
    ControlCenterTarget,
    ControlCenterTaskPresentation,
} from '../../control-center/types'
import type { SetupStyle } from '../../composables/useControlCenterSetupFlow'
import ControlCenterSetupWorkspace from './ControlCenterSetupWorkspace.vue'
import ConfigCapitalSection from '../config/ConfigCapitalSection.vue'
import ConfigDcaSection from '../config/ConfigDcaSection.vue'
import ConfigExchangeSection from '../config/ConfigExchangeSection.vue'
import ConfigMonitoringSection from '../config/ConfigMonitoringSection.vue'
import ConfigSignalSection from '../config/ConfigSignalSection.vue'

type BackupRestoreMode = 'config' | 'full'
interface SetupTaskStatus {
    label: string
    type: 'default' | 'info' | 'warning' | 'success'
}

defineProps<{
    activeTarget: ControlCenterTarget
    activationDisabled: boolean
    activationLoading: boolean
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
    dryRunActivationLocked: boolean
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
    liveActivationAvailable: boolean
    market: StringSelectOption[]
    monitoring: MonitoringModel
    monitoringFormRef?: VNodeRef
    monitoringTestLoading: boolean
    readinessComplete: boolean
    readinessFirstRun: boolean
    restoreLoading: boolean
    restoreReview: RestoreReviewState | null
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
    tradeModeSwitchGuard: TradeModeSwitchGuardState
    timezone: StringSelectOption[]
}>()

const emit = defineEmits<{
    'activate-live': []
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
        :active-target="activeTarget"
        :bind-backup-file-input="bindBackupFileInput"
        :bind-target-element="bindTargetElement"
        :get-setup-task-status="getSetupTaskStatus"
        :get-setup-task-summary="getSetupTaskSummary"
        :has-selected-backup-payload="hasSelectedBackupPayload"
        :is-setup-task-expanded="isSetupTaskExpanded"
        :live-activation-available="liveActivationAvailable"
        :readiness-complete="readinessComplete"
        :readiness-first-run="readinessFirstRun"
        :restore-loading="restoreLoading"
        :restore-review="restoreReview"
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

        <template #exchange>
            <ConfigExchangeSection
                :ref="exchangeFormRef"
                :timezone="timezone"
                :currency="currency"
                :dry-run-activation-locked="dryRunActivationLocked"
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
                 ref="dcaFormRef"
                 :dca="dca"
                 :rules="rules"
                 :sell-order-type-options="sellOrderTypeOptions"
                 :show-advanced-general="setupShowsAdvancedFields"
                 :strategy-options="signal.strategy_plugins"
                 :trade-mode-switch-guard="tradeModeSwitchGuard"
            />
        </template>

        <template #capital>
            <ConfigCapitalSection
                :ref="capitalFormRef"
                :capital="capital"
                :base-order-size="dca.bo"
                :max-safety-orders="dca.mstc"
                :quote-currency="exchange.currency"
                :card-title="null"
                :show-expert-fields="setupShowsAdvancedFields"
                :dynamic-dca-enabled="
                    dca.enabled && dca.trade_mode === 'dynamic_dca'
                "
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
        <template #readiness-review>
            <section
                id="control-center-live-activation"
                :ref="bindTargetElement('live-activation')"
                class="readiness-review dashboard-panel"
                aria-labelledby="readiness-review-title"
            >
                <div>
                    <p class="readiness-kicker">Final step</p>
                    <h2 id="readiness-review-title">Readiness review</h2>
                    <p>Configuration is saved and Moonwalker is operating in dry run. Activating live trading will submit orders to the configured exchange.</p>
                    <p v-if="activationDisabled" class="readiness-caution">
                        Save changes or reload the latest configuration before activating live trading.
                    </p>
                </div>
                <n-button
                    type="primary"
                    strong
                    :loading="activationLoading"
                    :disabled="activationDisabled"
                    @click="emit('activate-live')"
                >
                    Activate live trading
                </n-button>
            </section>
        </template>
    </ControlCenterSetupWorkspace>
</template>

<style scoped>
.readiness-review {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 20px;
    padding: 20px;
}
.readiness-review h2 {
    margin: 0 0 6px;
    font-family: var(--mw-font-display);
    font-size: 1.25rem;
}
.readiness-review p {
    max-width: 66ch;
    margin: 0;
    color: var(--mw-color-text-secondary);
    line-height: 1.5;
}
.readiness-review .readiness-kicker {
    margin-bottom: 6px;
    color: var(--mw-color-primary);
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
}
.readiness-review .readiness-caution {
    margin-top: 8px;
    color: var(--mw-color-warning);
}
@media (max-width: 767px) {
    .readiness-review { align-items: stretch; flex-direction: column; }
    .readiness-review :deep(.n-button) { min-height: 44px; }
}
</style>
