import axios from 'axios'
import type { Ref } from 'vue'

import {
    buildLoadedConfigState,
    type ConfigLoadDefaults,
    type LoadedSignalConfigSection,
} from '../helpers/configLoad'
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
    syncBaselineState: () => void
}

export function useConfigLoadFlow(options: UseConfigLoadFlowOptions) {
    async function fetchDefaultValues(): Promise<void> {
        options.isLoading.value = true

        try {
            const response = await axios.get(options.apiUrl('/config/all'))
            if (response.status === 200) {
                const defaults = options.buildDefaults()
                const loadedConfig = buildLoadedConfigState(
                    response.data,
                    defaults,
                )

                Object.assign(options.general.value, loadedConfig.general)
                Object.assign(options.signal.value, loadedConfig.signal)
                Object.assign(options.filter.value, loadedConfig.filter)
                Object.assign(options.exchange.value, loadedConfig.exchange)
                Object.assign(options.dca.value, loadedConfig.dca)
                Object.assign(options.autopilot.value, loadedConfig.autopilot)
                Object.assign(options.monitoring.value, loadedConfig.monitoring)
                Object.assign(options.indicator.value, loadedConfig.indicator)
                options.showAdvancedGeneral.value =
                    loadedConfig.showAdvancedGeneral

                await options.onAfterLoad?.()

                options.syncBaselineState()
                options.resetSaveState()
                trackUiEvent('config_baseline_loaded')
            } else {
                options.message.error('Failed to load default values')
                options.setSaveError('Failed to load configuration.')
            }
        } catch (error) {
            console.error('Error fetching default values:', error)
            options.message.error(
                'An unexpected error occurred while loading default values.',
            )
            options.setSaveError(
                'An unexpected error occurred while loading default values.',
            )
        } finally {
            options.isLoading.value = false
        }
    }

    return {
        fetchDefaultValues,
    }
}
