import { ref } from 'vue'

import { trackUiEvent } from '../utils/uiTelemetry'

export interface ConfigSectionFormExpose {
    validate: () => Promise<boolean>
}

interface MessageApiLike {
    error: (message: string) => void
}

interface UseConfigValidationFlowOptions {
    message: MessageApiLike
    onValidSubmit: () => Promise<void> | void
    onInvalid?: (sectionKey: string) => Promise<void> | void
    setSaveError: (message: string) => void
}

export function useConfigValidationFlow(
    options: UseConfigValidationFlowOptions,
) {
    const generalFormRef = ref<ConfigSectionFormExpose | null>(null)
    const signalFormRef = ref<ConfigSectionFormExpose | null>(null)
    const filterFormRef = ref<ConfigSectionFormExpose | null>(null)
    const exchangeFormRef = ref<ConfigSectionFormExpose | null>(null)
    const dcaFormRef = ref<ConfigSectionFormExpose | null>(null)
    const autopilotFormRef = ref<ConfigSectionFormExpose | null>(null)
    const monitoringFormRef = ref<ConfigSectionFormExpose | null>(null)
    const indicatorFormRef = ref<ConfigSectionFormExpose | null>(null)
    const submitAttempted = ref(false)

    async function validateAndSubmit(): Promise<{
        valid: boolean
        invalidSection: string | null
    }> {
        submitAttempted.value = true

        const sectionForms = [
            ['general', generalFormRef.value],
            ['signal', signalFormRef.value],
            ['filter', filterFormRef.value],
            ['exchange', exchangeFormRef.value],
            ['dca', dcaFormRef.value],
            ['autopilot', autopilotFormRef.value],
            ['monitoring', monitoringFormRef.value],
            ['indicator', indicatorFormRef.value],
        ].filter(
            (
                entry,
            ): entry is [string, ConfigSectionFormExpose] => entry[1] !== null,
        )

        const results = await Promise.all(
            sectionForms.map(([, form]) => form.validate()),
        )

        if (results.every(Boolean)) {
            trackUiEvent('config_validation_success')
            await options.onValidSubmit()
            return {
                valid: true,
                invalidSection: null,
            }
        }

        const invalidIndex = results.findIndex((result) => !result)
        const invalidSection = sectionForms[invalidIndex]?.[0] ?? null
        options.setSaveError('Missing/invalid configuration input')
        trackUiEvent('config_validation_failed')
        options.message.error('Missing/invalid configuration input')
        if (invalidSection) {
            await options.onInvalid?.(invalidSection)
        }
        return {
            valid: false,
            invalidSection,
        }
    }

    function handleValidateButtonClick(event: MouseEvent): void {
        event.preventDefault()
        void validateAndSubmit()
    }

    function handleGlobalKeydown(event: KeyboardEvent): void {
        const key = event.key.toLowerCase()
        if ((event.ctrlKey || event.metaKey) && key === 's') {
            event.preventDefault()
            trackUiEvent('config_submit_shortcut_used')
            void validateAndSubmit()
        }
    }

    return {
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
        validateAndSubmit,
    }
}
