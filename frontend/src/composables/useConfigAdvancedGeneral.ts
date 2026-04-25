import { watch, type Ref } from 'vue'

import type { ConfigLoadDefaults } from '../helpers/configLoad'
import type {
    ConfigSubmitPayloadDefaults,
    GeneralConfigSection,
} from '../helpers/configSubmitPayload'

interface UseConfigAdvancedGeneralOptions {
    advancedPreferenceKey: string
    defaultSymSignalUrl: string
    defaultSymSignalVersion: string
    defaults: ConfigSubmitPayloadDefaults
    general: Ref<GeneralConfigSection>
    getClientTimezone: () => string
    isLoading: Ref<boolean>
    showAdvancedGeneral: Ref<boolean>
}

function getStoredAdvancedGeneralPreference(preferenceKey: string): boolean {
    const raw = localStorage.getItem(preferenceKey)
    return raw === 'true'
}

export function useConfigAdvancedGeneral(
    options: UseConfigAdvancedGeneralOptions,
) {
    function buildConfigLoadDefaults(): ConfigLoadDefaults {
        return {
            clientTimezone: options.getClientTimezone(),
            showAdvancedGeneral: getStoredAdvancedGeneralPreference(
                options.advancedPreferenceKey,
            ),
            advancedWsHealthcheckIntervalMs:
                options.defaults.advancedWsHealthcheckIntervalMs,
            advancedWsStaleTimeoutMs: options.defaults.advancedWsStaleTimeoutMs,
            advancedWsReconnectDebounceMs:
                options.defaults.advancedWsReconnectDebounceMs,
            defaultSymSignalUrl: options.defaultSymSignalUrl,
            defaultSymSignalVersion: options.defaultSymSignalVersion,
            defaultTpSpikeConfirmSeconds:
                options.defaults.defaultTpSpikeConfirmSeconds,
            defaultTpSpikeConfirmTicks:
                options.defaults.defaultTpSpikeConfirmTicks,
            defaultGreenPhaseRampDays: options.defaults.defaultGreenPhaseRampDays,
            defaultGreenPhaseEvalIntervalSec:
                options.defaults.defaultGreenPhaseEvalIntervalSec,
            defaultGreenPhaseWindowMinutes:
                options.defaults.defaultGreenPhaseWindowMinutes,
            defaultGreenPhaseMinProfitableCloseRatio:
                options.defaults.defaultGreenPhaseMinProfitableCloseRatio,
            defaultGreenPhaseSpeedMultiplier:
                options.defaults.defaultGreenPhaseSpeedMultiplier,
            defaultGreenPhaseExitMultiplier:
                options.defaults.defaultGreenPhaseExitMultiplier,
            defaultGreenPhaseMaxExtraDeals:
                options.defaults.defaultGreenPhaseMaxExtraDeals,
            defaultGreenPhaseConfirmCycles:
                options.defaults.defaultGreenPhaseConfirmCycles,
            defaultGreenPhaseReleaseCycles:
                options.defaults.defaultGreenPhaseReleaseCycles,
            defaultGreenPhaseMaxLockedFundPercent:
                options.defaults.defaultGreenPhaseMaxLockedFundPercent,
            defaultAutopilotProfitStretchRatio:
                options.defaults.defaultAutopilotProfitStretchRatio,
            defaultAutopilotProfitStretchMax:
                options.defaults.defaultAutopilotProfitStretchMax,
            defaultAutopilotEntryStretchMaxMultiplier:
                options.defaults.defaultAutopilotEntryStretchMaxMultiplier,
            defaultAutopilotSafetyStretchMaxMultiplier:
                options.defaults.defaultAutopilotSafetyStretchMaxMultiplier,
        }
    }

    watch(
        () => options.showAdvancedGeneral.value,
        (enabled) => {
            if (options.isLoading.value) {
                return
            }
            localStorage.setItem(
                options.advancedPreferenceKey,
                enabled ? 'true' : 'false',
            )
        },
    )

    return {
        buildConfigLoadDefaults,
    }
}
