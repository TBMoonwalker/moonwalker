import axios from 'axios'
import type { Ref } from 'vue'

import {
    buildLoadedConfigState,
    type ConfigLoadDefaults,
    type LoadedSignalConfigSection,
} from '../helpers/configLoad'
import type { OperationResult } from '../control-center/operationResults'
import type {
    AutopilotConfigSection,
    DcaConfigSection,
    ExchangeConfigSection,
    FilterConfigSection,
    GeneralConfigSection,
    IndicatorConfigSection,
    MonitoringConfigSection,
} from '../helpers/configSubmitPayload'
import { trackUiEvent } from '../utils/uiTelemetry'

interface MessageApiLike {
    error: (message: string) => void
}

interface UseConfigLoadFlowOptions {
    apiUrl: (path: string) => string
    buildDefaults: () => ConfigLoadDefaults
    loadConfig?: () => Promise<Record<string, unknown> | null>
    general: Ref<GeneralConfigSection>
    signal: Ref<LoadedSignalConfigSection>
    filter: Ref<FilterConfigSection>
    exchange: Ref<ExchangeConfigSection>
    dca: Ref<DcaConfigSection>
    autopilot: Ref<AutopilotConfigSection>
    monitoring: Ref<MonitoringConfigSection>
    indicator: Ref<IndicatorConfigSection>
    showAdvancedGeneral: Ref<boolean>
    isLoading: Ref<boolean>
    message: MessageApiLike
    onAfterLoad?: () => Promise<void> | void
    resetSaveState: () => void
    setSaveError: (message: string) => void
    surfaceMessages?: boolean
    syncBaselineState: () => void
}

export function useConfigLoadFlow(options: UseConfigLoadFlowOptions) {
    async function fetchDefaultValues(): Promise<OperationResult> {
        options.isLoading.value = true

        try {
            const payload = options.loadConfig
                ? await options.loadConfig()
                : (
                      await axios.get<Record<string, unknown>>(
                          options.apiUrl('/config/all'),
                      )
                  ).data
            if (!payload) {
                const message = 'Failed to load configuration.'
                options.setSaveError(message)
                if (options.surfaceMessages !== false) {
                    options.message.error(message)
                }
                return {
                    status: 'error',
                    message,
                }
            }

            const defaults = options.buildDefaults()
            const loadedConfig = buildLoadedConfigState(payload, defaults)

            Object.assign(options.general.value, loadedConfig.general)
            Object.assign(options.signal.value, loadedConfig.signal)
            Object.assign(options.filter.value, loadedConfig.filter)
            Object.assign(options.exchange.value, loadedConfig.exchange)
            Object.assign(options.dca.value, loadedConfig.dca)
            Object.assign(options.autopilot.value, loadedConfig.autopilot)
            Object.assign(options.monitoring.value, loadedConfig.monitoring)
            Object.assign(options.indicator.value, loadedConfig.indicator)
            options.showAdvancedGeneral.value = loadedConfig.showAdvancedGeneral

            await options.onAfterLoad?.()

            options.syncBaselineState()
            options.resetSaveState()
            trackUiEvent('config_baseline_loaded')
            return {
                status: 'success',
                message: 'Configuration loaded.',
            }
        } catch (error) {
            console.error('Error fetching default values:', error)
            const message =
                'An unexpected error occurred while loading default values.'
            if (options.surfaceMessages !== false) {
                options.message.error(message)
            }
            options.setSaveError(message)
            return {
                status: 'error',
                message,
            }
        } finally {
            options.isLoading.value = false
        }
    }

    return {
        fetchDefaultValues,
    }
}
