<template>
    <n-flex vertical class="config-form-shell">
        <ConfigGeneralSection
            ref="generalFormRef"
            :general="general"
            :rules="rules"
            :show-advanced-general="showAdvancedGeneral"
            :timezone="timezone"
            @update:show-advanced-general="showAdvancedGeneral = $event"
        />

        

        <ConfigExchangeSection
            ref="exchangeFormRef"
            :currency="currency"
            :exchange="exchange"
            :exchanges="exchanges"
            :market="market"
            :rules="rules"
            :show-advanced-general="showAdvancedGeneral"
            :timerange="timerange"
        />

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

        <ConfigFilterSection
            ref="filterFormRef"
            :filter="filter"
            :rules="rules"
            :show-asap-fields="signal.signal === 'asap'"
        />

        

        <ConfigDcaSection
            ref="dcaFormRef"
            :dca="dca"
            :rules="rules"
            :sell-order-type-options="sellOrderTypeOptions"
            :show-advanced-general="showAdvancedGeneral"
            :strategy-options="signal.strategy_plugins"
        />

        <ConfigAutopilotSection
            ref="autopilotFormRef"
            :autopilot="autopilot"
            :rules="rules"
            :show-fields="autopilot.enabled"
        />

        <ConfigMonitoringSection
            ref="monitoringFormRef"
            :can-test="canTestMonitoringTelegram()"
            :monitoring="monitoring"
            :on-test="testMonitoringTelegram"
            :rules="rules"
            :test-loading="monitoringTestLoading"
        />

        <ConfigIndicatorSection
            ref="indicatorFormRef"
            :history-lookback-options="historyLookbackOptions"
            :indicator="indicator"
            :rules="rules"
        />

        <n-card title="Backup & Restore" size="small" class="backup-restore-card">
            <n-flex vertical :size="12">
                <n-alert type="info" title="Portable backup">
                    Download your configuration alone or include all trade data. Full restores do not import ticker candles and will fetch the required history again for restored active trades.
                </n-alert>

                <n-flex align="center" :wrap="true" :size="[12, 12]">
                    <n-checkbox v-model:checked="backupIncludeTradeData">
                        Include trade data in backup
                    </n-checkbox>
                    <n-button
                        type="primary"
                        secondary
                        :loading="backupDownloadLoading"
                        @click="handleBackupDownload"
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
                        @click="handleRestoreBackup('config')"
                    >
                        Restore config only
                    </n-button>
                    <n-button
                        type="error"
                        ghost
                        :loading="restoreLoading"
                        :disabled="!selectedBackupHasTradeData"
                        @click="handleRestoreBackup('full')"
                    >
                        Restore full backup
                    </n-button>
                </n-flex>
            </n-flex>
        </n-card>

        <n-alert
            :type="saveBannerType"
            :title="saveBannerTitle"
            role="status"
            aria-live="polite"
        >
            {{ saveBannerMessage }}
        </n-alert>

        <n-button
            class="submit-button"
            round
            type="primary"
            :loading="saveState === 'saving'"
            :disabled="isSubmitDisabled"
            aria-label="Submit configuration changes"
            aria-keyshortcuts="Control+S Meta+S"
            @click="handleValidateButtonClick"
        >
            {{ submitButtonLabel }}
        </n-button>
    </n-flex>

</template>

<script setup lang="ts">
import ConfigAutopilotSection from './config/ConfigAutopilotSection.vue'
import ConfigDcaSection from './config/ConfigDcaSection.vue'
import ConfigExchangeSection from './config/ConfigExchangeSection.vue'
import ConfigFilterSection from './config/ConfigFilterSection.vue'
import ConfigGeneralSection from './config/ConfigGeneralSection.vue'
import ConfigIndicatorSection from './config/ConfigIndicatorSection.vue'
import ConfigMonitoringSection from './config/ConfigMonitoringSection.vue'
import ConfigSignalSection from './config/ConfigSignalSection.vue'
import { useConfigAdvancedGeneral } from '../composables/useConfigAdvancedGeneral'
import { useConfigBackupRestore } from '../composables/useConfigBackupRestore'
import { useConfigLoadFlow } from '../composables/useConfigLoadFlow'
import { useConfigMonitoringTest } from '../composables/useConfigMonitoringTest'
import { useConfigPageState } from '../composables/useConfigPageState'
import { useConfigPersistableState } from '../composables/useConfigPersistableState'
import { useConfigSaveFlow } from '../composables/useConfigSaveFlow'
import { useConfigSignalFlow } from '../composables/useConfigSignalFlow'
import { useConfigValidationFlow } from '../composables/useConfigValidationFlow'
import {
    buildMoonwalkerApiUrl,
    CONFIG_ADVANCED_GENERAL_PREFERENCE_KEY,
    CONFIG_DEFAULT_SYMSIGNAL_URL,
    CONFIG_DEFAULT_SYMSIGNAL_VERSION,
    CONFIG_SUBMIT_PAYLOAD_DEFAULTS,
    getClientTimezone,
} from '../helpers/configEditorDefaults'
import { buildConfigRules } from '../helpers/configRules'
import { buildConfigSubmitPayload } from '../helpers/configSubmitPayload'
import { useMessage } from 'naive-ui/es/message'
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { onBeforeRouteLeave, useRouter } from 'vue-router'

const message = useMessage()
const router = useRouter()
const isLoading = ref(true)
const showAdvancedGeneral = ref(false)
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
    defaults: CONFIG_SUBMIT_PAYLOAD_DEFAULTS,
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
    advancedPreferenceKey: CONFIG_ADVANCED_GENERAL_PREFERENCE_KEY,
    defaultSymSignalUrl: CONFIG_DEFAULT_SYMSIGNAL_URL,
    defaultSymSignalVersion: CONFIG_DEFAULT_SYMSIGNAL_VERSION,
    defaults: CONFIG_SUBMIT_PAYLOAD_DEFAULTS,
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
    saveBannerMessage,
    saveBannerTitle,
    saveBannerType,
    saveState,
    setSaveError,
    submitButtonLabel,
    submitForm,
} = useConfigSaveFlow({
    apiUrl: buildMoonwalkerApiUrl,
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
            showAdvancedGeneral: showAdvancedGeneral.value,
            defaults: CONFIG_SUBMIT_PAYLOAD_DEFAULTS,
        }),
    changedSectionLabels,
    changedSections,
    isDirty,
    isLoading,
    message,
    onSaved: () => {
        setTimeout(() => {
            router.push('/')
        }, 250)
    },
    syncBaselineState,
})
const {
    autopilotFormRef,
    dcaFormRef,
    exchangeFormRef,
    filterFormRef,
    generalFormRef,
    handleGlobalKeydown,
    handleValidateButtonClick,
    indicatorFormRef,
    monitoringFormRef,
    signalFormRef,
    submitAttempted,
} = useConfigValidationFlow({
    message,
    onValidSubmit: submitForm,
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
    apiUrl: buildMoonwalkerApiUrl,
    defaultSymSignalUrl: CONFIG_DEFAULT_SYMSIGNAL_URL,
    defaultSymSignalVersion: CONFIG_DEFAULT_SYMSIGNAL_VERSION,
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
    apiUrl: buildMoonwalkerApiUrl,
    hasUnsavedChanges,
    message,
    onBeforeReload: () => {
        isLoading.value = true
    },
    reloadConfig: () => fetchDefaultValues(),
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
    apiUrl: buildMoonwalkerApiUrl,
    buildDefaults: buildConfigLoadDefaults,
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
    syncBaselineState,
})
const {
    canTestMonitoringTelegram,
    monitoringTestLoading,
    testMonitoringTelegram,
} = useConfigMonitoringTest({
    apiUrl: buildMoonwalkerApiUrl,
    message,
    monitoring,
})

onBeforeRouteLeave(() => confirmDiscardUnsavedChanges('route_leave'))

onMounted(() => {
    initializeTimezoneOptions(getClientTimezone())
    window.addEventListener('beforeunload', handleBeforeUnload)
    window.addEventListener('keydown', handleGlobalKeydown)
    void fetchDefaultValues()
})

onUnmounted(() => {
    window.removeEventListener('beforeunload', handleBeforeUnload)
    window.removeEventListener('keydown', handleGlobalKeydown)
})

</script>

<style scoped>
.config-form-shell {
    display: flex;
    flex-direction: column;
    gap: 16px;
    width: 100%;
}

.backup-restore-card {
    width: 100%;
}

.backup-file-input {
    display: none;
}

.backup-file-name {
    font-size: 14px;
}

@media (max-width: 768px) {
    .submit-button {
        width: 100%;
    }
}
</style>
