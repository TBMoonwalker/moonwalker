import axios from 'axios'
import { computed, ref, type ComputedRef, type Ref } from 'vue'

import { trackUiEvent } from '../utils/uiTelemetry'

type SaveState = 'idle' | 'saving' | 'saved' | 'error'

type DiscardSource = 'route_leave' | 'page_unload'

interface MessageApiLike {
    error: (message: string) => void
    info: (message: string) => void
    success: (message: string) => void
}

interface UseConfigSaveFlowOptions<TPayload> {
    apiUrl: (path: string) => string
    buildPayload: () => TPayload
    changedSectionLabels: ComputedRef<string[]>
    changedSections: ComputedRef<string[]>
    isDirty: ComputedRef<boolean>
    isLoading: Ref<boolean>
    message: MessageApiLike
    onSaved?: () => void
    syncBaselineState: () => void
}

function extractAxiosErrorMessage(error: unknown, fallback: string): string {
    if (axios.isAxiosError(error)) {
        if (error.response?.data?.message) {
            return String(error.response.data.message)
        }
        if (error.response?.data) {
            try {
                return JSON.stringify(error.response.data)
            } catch {
                return fallback
            }
        }
        if (error.message) {
            return error.message
        }
    }
    if (error instanceof Error && error.message) {
        return error.message
    }
    return fallback
}

export function useConfigSaveFlow<TPayload>(
    options: UseConfigSaveFlowOptions<TPayload>,
) {
    const saveState = ref<SaveState>('idle')
    const saveErrorMessage = ref<string | null>(null)
    const lastSavedAt = ref<Date | null>(null)

    const submitButtonLabel = computed(() => {
        if (saveState.value === 'saving') {
            return 'Saving...'
        }
        if (options.isDirty.value) {
            return 'Submit changes'
        }
        return 'No changes'
    })

    const saveBannerType = computed(() => {
        if (saveState.value === 'error') {
            return 'error'
        }
        if (saveState.value === 'saved') {
            return 'success'
        }
        if (options.isDirty.value) {
            return 'warning'
        }
        return 'info'
    })

    const saveBannerTitle = computed(() => {
        if (saveState.value === 'error') {
            return 'Save failed'
        }
        if (saveState.value === 'saved') {
            return 'Saved'
        }
        if (options.isDirty.value) {
            return 'Unsaved changes'
        }
        return 'No pending changes'
    })

    const saveBannerMessage = computed(() => {
        if (saveState.value === 'error' && saveErrorMessage.value) {
            return saveErrorMessage.value
        }
        if (saveState.value === 'saved' && lastSavedAt.value) {
            return `Settings saved at ${lastSavedAt.value.toLocaleTimeString()}`
        }
        if (options.isDirty.value) {
            const changed = options.changedSectionLabels.value.join(', ')
            return changed.length > 0
                ? `Changed sections: ${changed}`
                : 'You have unsaved changes.'
        }
        return 'Edit any field and submit to persist updates.'
    })

    const isSubmitDisabled = computed(
        () =>
            options.isLoading.value ||
            saveState.value === 'saving' ||
            !options.isDirty.value,
    )

    function hasUnsavedChanges(): boolean {
        return !options.isLoading.value && options.isDirty.value
    }

    function setSaveError(messageText: string): void {
        saveState.value = 'error'
        saveErrorMessage.value = messageText
    }

    function resetSaveState(): void {
        saveState.value = 'idle'
        saveErrorMessage.value = null
        lastSavedAt.value = null
    }

    function confirmDiscardUnsavedChanges(source: DiscardSource): boolean {
        if (!hasUnsavedChanges()) {
            return true
        }
        if (source === 'page_unload') {
            return false
        }
        const confirmLeave = window.confirm(
            'You have unsaved changes. Leave this page and discard them?',
        )
        trackUiEvent('config_unsaved_prompt', {
            source,
            confirmed: confirmLeave,
            dirty_sections: options.changedSections.value.length,
        })
        return confirmLeave
    }

    function handleBeforeUnload(event: BeforeUnloadEvent): void {
        if (confirmDiscardUnsavedChanges('page_unload')) {
            return
        }
        event.preventDefault()
        event.returnValue = ''
    }

    async function submitForm(): Promise<void> {
        if (!options.isDirty.value) {
            options.message.info('No unsaved changes to submit.')
            trackUiEvent('config_submit_skipped_no_changes')
            return
        }
        if (saveState.value === 'saving') {
            return
        }

        const submitStartedAt = performance.now()
        const dirtySectionsBeforeSubmit = options.changedSections.value.length
        trackUiEvent('config_submit_requested')
        saveState.value = 'saving'
        saveErrorMessage.value = null

        try {
            const response = await axios.post(
                options.apiUrl('/config/multiple'),
                options.buildPayload(),
            )

            if (response.status >= 200 && response.status < 300) {
                options.syncBaselineState()
                saveState.value = 'saved'
                saveErrorMessage.value = null
                lastSavedAt.value = new Date()
                trackUiEvent('config_submit_success', {
                    status_code: response.status,
                    duration_ms: Math.round(performance.now() - submitStartedAt),
                    dirty_sections: dirtySectionsBeforeSubmit,
                })
                options.message.success('Form submitted successfully')
                options.onSaved?.()
                return
            }

            const errorMessage = extractAxiosErrorMessage(
                { response },
                'An unexpected error occurred while submitting the configuration.',
            )
            setSaveError(errorMessage)
            trackUiEvent('config_submit_error', {
                status_code: response.status,
                duration_ms: Math.round(performance.now() - submitStartedAt),
                category: 'non_2xx_response',
            })
            options.message.error(errorMessage)
        } catch (error) {
            const category = axios.isAxiosError(error)
                ? error.response
                    ? 'exception_response'
                    : error.request
                      ? 'no_response'
                      : 'request_setup'
                : 'request_setup'
            const statusCode =
                axios.isAxiosError(error) && error.response
                    ? error.response.status || null
                    : null
            const errorMessage =
                category === 'no_response'
                    ? 'No response from server. Please try again later.'
                    : category === 'request_setup'
                      ? `Request failed: ${extractAxiosErrorMessage(error, 'Unknown error')}`
                      : extractAxiosErrorMessage(
                            error,
                            'An unexpected error occurred',
                        )

            trackUiEvent('config_submit_error', {
                status_code: statusCode,
                duration_ms: Math.round(performance.now() - submitStartedAt),
                category,
            })
            setSaveError(errorMessage)
            options.message.error(errorMessage)
        }
    }

    return {
        confirmDiscardUnsavedChanges,
        handleBeforeUnload,
        hasUnsavedChanges,
        isSubmitDisabled,
        lastSavedAt,
        resetSaveState,
        saveBannerMessage,
        saveBannerTitle,
        saveBannerType,
        saveErrorMessage,
        saveState,
        setSaveError,
        submitButtonLabel,
        submitForm,
    }
}
