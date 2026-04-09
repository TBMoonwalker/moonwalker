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

        <n-card
            title="Backup & Restore"
            size="small"
            class="backup-restore-card mw-shell-card"
        >
            <n-flex vertical :size="12">
                <ConfigBackupDownloadControls
                    :backup-download-loading="backupDownloadLoading"
                    :backup-include-trade-data="backupIncludeTradeData"
                    info-title="Portable backup"
                    info-message="Download your configuration alone or include all trade data. Full restores do not import ticker candles and will fetch the required history again for restored active trades."
                    @download-backup="handleBackupDownload"
                    @update:backup-include-trade-data="backupIncludeTradeData = $event"
                />

                <n-divider />

                <ConfigBackupRestoreControls
                    :bind-backup-file-input="bindBackupFileInput"
                    :has-selected-backup-payload="!!selectedBackupPayload"
                    :restore-loading="restoreLoading"
                    :selected-backup-config-count="selectedBackupConfigCount"
                    :selected-backup-file-name="selectedBackupFileName"
                    :selected-backup-has-trade-data="selectedBackupHasTradeData"
                    @backup-file-selected="handleBackupFileSelected"
                    @clear-selected-backup="clearSelectedBackup"
                    @open-backup-file-picker="openBackupFilePicker"
                    @restore-backup="handleRestoreBackup"
                />
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
import ConfigBackupDownloadControls from './config/ConfigBackupDownloadControls.vue'
import ConfigBackupRestoreControls from './config/ConfigBackupRestoreControls.vue'
import ConfigDcaSection from './config/ConfigDcaSection.vue'
import ConfigExchangeSection from './config/ConfigExchangeSection.vue'
import ConfigFilterSection from './config/ConfigFilterSection.vue'
import ConfigGeneralSection from './config/ConfigGeneralSection.vue'
import ConfigIndicatorSection from './config/ConfigIndicatorSection.vue'
import ConfigMonitoringSection from './config/ConfigMonitoringSection.vue'
import ConfigSignalSection from './config/ConfigSignalSection.vue'
import { useConfigEditorAssembly } from '../composables/useConfigEditorAssembly'
import { useMessage } from 'naive-ui/es/message'
import { onMounted, onUnmounted } from 'vue'
import { onBeforeRouteLeave, useRouter } from 'vue-router'

const message = useMessage()
const router = useRouter()
const {
    autopilot,
    autopilotFormRef,
    backupDownloadLoading,
    backupIncludeTradeData,
    bindBackupFileInput,
    canTestMonitoringTelegram,
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
    handleValidateButtonClick,
    historyLookbackOptions,
    indicator,
    indicatorFormRef,
    initializeClientTimezoneOptions,
    isAsapExchangeReady,
    isSubmitDisabled,
    market,
    monitoring,
    monitoringFormRef,
    monitoringTestLoading,
    openBackupFilePicker,
    restoreLoading,
    rules,
    saveBannerMessage,
    saveBannerTitle,
    saveBannerType,
    saveState,
    sellOrderTypeOptions,
    selectedBackupConfigCount,
    selectedBackupFileName,
    selectedBackupHasTradeData,
    selectedBackupPayload,
    showAdvancedGeneral,
    signal,
    signalFormRef,
    submitButtonLabel,
    symsignals,
    testMonitoringTelegram,
    timerange,
    timezone,
} = useConfigEditorAssembly({
    message,
    save: {
        onSaved: () => {
            setTimeout(() => {
                router.push('/')
            }, 250)
        },
    },
})

onBeforeRouteLeave(() => confirmDiscardUnsavedChanges('route_leave'))

onMounted(() => {
    initializeClientTimezoneOptions()
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

@media (max-width: 768px) {
    .submit-button {
        width: 100%;
    }
}
</style>
