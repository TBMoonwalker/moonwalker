import { ref, type Ref } from 'vue'

import type { LoadedSignalConfigSection } from '../helpers/configLoad'
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
import type { OperationResult } from '../control-center/operationResults'
import { useConfigAdvancedGeneral } from './useConfigAdvancedGeneral'
import { useConfigBackupRestore } from './useConfigBackupRestore'
import { useConfigLoadFlow } from './useConfigLoadFlow'
import { useConfigMonitoringTest } from './useConfigMonitoringTest'
import { useConfigPageState } from './useConfigPageState'
import { useConfigPersistableState } from './useConfigPersistableState'
import { useConfigSaveFlow } from './useConfigSaveFlow'
import { useConfigSignalFlow } from './useConfigSignalFlow'
import { useConfigValidationFlow } from './useConfigValidationFlow'

interface ConfigEditorMessageApiLike {
    error: (message: string) => void
    info: (message: string) => void
    success: (message: string) => void
    warning: (message: string) => void
}

interface ConfigEditorSurfaceMessages {
    backupRestore?: boolean
    load?: boolean
    monitoring?: boolean
    save?: boolean
}

interface ConfigEditorBackupRestoreOptions {
    onBeforeReload?: () => void
    reloadConfig?: () => Promise<void>
}

interface ConfigEditorLoadOptions {
    loadConfig?: () => Promise<Record<string, unknown> | null>
    onAfterLoad?: () => Promise<void> | void
}

interface ConfigEditorSaveOptions {
    onSaved?: () => Promise<void> | void
}

interface ConfigEditorValidationOptions {
    onInvalid?: (sectionKey: string) => Promise<void> | void
    onSubmitShortcut?: () => Promise<void> | void
    onValidSubmit?: () => Promise<void> | void
}

interface UseConfigEditorAssemblyOptions {
    backupRestore?: ConfigEditorBackupRestoreOptions
    load?: ConfigEditorLoadOptions
    message: ConfigEditorMessageApiLike
    readSubmitShowAdvancedGeneral?: () => boolean
    save?: ConfigEditorSaveOptions
    surfaceMessages?: ConfigEditorSurfaceMessages
    validation?: ConfigEditorValidationOptions
}

type ConfigLoader = () => Promise<OperationResult>

export function useConfigEditorAssembly(
    options: UseConfigEditorAssemblyOptions,
) {
    const isLoading = ref(true)
    const showAdvancedGeneral = ref(false)

    const pageState = useConfigPageState({
        defaults: CONFIG_SUBMIT_PAYLOAD_DEFAULTS,
    })
    const persistableState = useConfigPersistableState({
        autopilot: pageState.autopilot,
        dca: pageState.dca,
        exchange: pageState.exchange,
        filter: pageState.filter,
        general: pageState.general,
        indicator: pageState.indicator,
        monitoring: pageState.monitoring,
        signal: pageState.signal as Ref<LoadedSignalConfigSection>,
    })

    const { buildConfigLoadDefaults } = useConfigAdvancedGeneral({
        advancedPreferenceKey: CONFIG_ADVANCED_GENERAL_PREFERENCE_KEY,
        defaultSymSignalUrl: CONFIG_DEFAULT_SYMSIGNAL_URL,
        defaultSymSignalVersion: CONFIG_DEFAULT_SYMSIGNAL_VERSION,
        defaults: CONFIG_SUBMIT_PAYLOAD_DEFAULTS,
        general: pageState.general,
        getClientTimezone,
        isLoading,
        showAdvancedGeneral,
    })

    const saveFlow = useConfigSaveFlow({
        apiUrl: buildMoonwalkerApiUrl,
        buildPayload: () =>
            buildConfigSubmitPayload({
                general: pageState.general.value,
                signal: pageState.signal.value,
                filter: pageState.filter.value,
                exchange: pageState.exchange.value,
                dca: pageState.dca.value,
                autopilot: pageState.autopilot.value,
                monitoring: pageState.monitoring.value,
                indicator: pageState.indicator.value,
                showAdvancedGeneral:
                    options.readSubmitShowAdvancedGeneral?.() ??
                    showAdvancedGeneral.value,
                defaults: CONFIG_SUBMIT_PAYLOAD_DEFAULTS,
            }),
        changedSectionLabels: persistableState.changedSectionLabels,
        changedSections: persistableState.changedSections,
        isDirty: persistableState.isDirty,
        isLoading,
        message: options.message,
        onSaved: options.save?.onSaved,
        surfaceMessages: options.surfaceMessages?.save,
        syncBaselineState: persistableState.syncBaselineState,
    })

    const validationFlow = useConfigValidationFlow({
        message: options.message,
        onInvalid: options.validation?.onInvalid,
        onSubmitShortcut: options.validation?.onSubmitShortcut,
        onValidSubmit: options.validation?.onValidSubmit ?? saveFlow.submitForm,
        setSaveError: saveFlow.setSaveError,
    })

    const signalFlow = useConfigSignalFlow({
        apiUrl: buildMoonwalkerApiUrl,
        defaultSymSignalUrl: CONFIG_DEFAULT_SYMSIGNAL_URL,
        defaultSymSignalVersion: CONFIG_DEFAULT_SYMSIGNAL_VERSION,
        exchange: pageState.exchange,
        isLoading,
        message: options.message,
        resetSignalStrategySelection: pageState.resetSignalStrategySelection,
        signal: pageState.signal,
    })

    let fetchDefaultValues: ConfigLoader = async () => ({
        status: 'noop',
        message: 'Configuration loader not initialized.',
    })

    const backupRestoreFlow = useConfigBackupRestore({
        apiUrl: buildMoonwalkerApiUrl,
        hasUnsavedChanges: saveFlow.hasUnsavedChanges,
        message: options.message,
        onBeforeReload: () => {
            isLoading.value = true
            options.backupRestore?.onBeforeReload?.()
        },
        reloadConfig: async () => {
            if (options.backupRestore?.reloadConfig) {
                await options.backupRestore.reloadConfig()
                return
            }
            await fetchDefaultValues()
        },
        surfaceMessages: options.surfaceMessages?.backupRestore,
    })

    const rules = buildConfigRules({
        dca: pageState.dca,
        getAsapMissingFieldsLabel: signalFlow.getAsapMissingFieldsLabel,
        isAsapExchangeReady: signalFlow.isAsapExchangeReady,
        isCurrencyConfigured: signalFlow.isCurrencyConfigured,
        isUrlInput: signalFlow.isUrlInput,
        signal: pageState.signal,
        submitAttempted: validationFlow.submitAttempted,
    })

    const loadFlow = useConfigLoadFlow({
        apiUrl: buildMoonwalkerApiUrl,
        buildDefaults: buildConfigLoadDefaults,
        loadConfig: options.load?.loadConfig,
        general: pageState.general,
        signal: pageState.signal,
        filter: pageState.filter,
        exchange: pageState.exchange,
        dca: pageState.dca,
        autopilot: pageState.autopilot,
        monitoring: pageState.monitoring,
        indicator: pageState.indicator,
        showAdvancedGeneral,
        isLoading,
        message: options.message,
        onAfterLoad: async () => {
            if (pageState.signal.value.strategy) {
                pageState.signal.value.strategy_enabled = true
            }
            await signalFlow.applySignalSettingsSelection({
                awaitAsapFetch: true,
            })
            await options.load?.onAfterLoad?.()
        },
        resetSaveState: saveFlow.resetSaveState,
        setSaveError: saveFlow.setSaveError,
        surfaceMessages: options.surfaceMessages?.load,
        syncBaselineState: persistableState.syncBaselineState,
    })
    fetchDefaultValues = loadFlow.fetchDefaultValues

    const monitoringFlow = useConfigMonitoringTest({
        apiUrl: buildMoonwalkerApiUrl,
        message: options.message,
        monitoring: pageState.monitoring,
        surfaceMessages: options.surfaceMessages?.monitoring,
    })

    function initializeClientTimezoneOptions(): void {
        pageState.initializeTimezoneOptions(getClientTimezone())
    }

    return {
        ...pageState,
        ...persistableState,
        ...saveFlow,
        ...validationFlow,
        ...signalFlow,
        ...backupRestoreFlow,
        ...monitoringFlow,
        fetchDefaultValues,
        initializeClientTimezoneOptions,
        isLoading,
        rules,
        showAdvancedGeneral,
    }
}
