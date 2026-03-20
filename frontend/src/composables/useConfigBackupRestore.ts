import axios from 'axios'
import { computed, ref } from 'vue'

import type { OperationResult } from '../control-center/operationResults'

type BackupRestoreMode = 'config' | 'full'

type BackupPayload = {
    config?: unknown
    trade_data?: unknown
    includes_trade_data?: boolean
}

type RestoreSummary = {
    config_keys?: number
    history_refreshed_symbols?: string[]
    history_failed_symbols?: string[]
}

type RestoreResponse = {
    message?: string
    result?: RestoreSummary
}

interface MessageApiLike {
    error: (message: string) => void
    success: (message: string) => void
    warning: (message: string) => void
}

interface UseConfigBackupRestoreOptions {
    apiUrl: (path: string) => string
    hasUnsavedChanges: () => boolean
    message: MessageApiLike
    onBeforeReload: () => void
    reloadConfig: () => Promise<void>
    surfaceMessages?: boolean
}

function isBackupPayload(value: unknown): value is BackupPayload {
    return typeof value === 'object' && value !== null && 'config' in value
}

function buildBackupFilename(includeTradeData: boolean): string {
    const timestamp = new Date().toISOString().replaceAll(':', '-')
    const scope = includeTradeData ? 'full' : 'config'
    return `moonwalker-backup-${scope}-${timestamp}.json`
}

function downloadTextFile(filename: string, content: string): void {
    const blob = new Blob([content], { type: 'application/json;charset=utf-8' })
    const url = window.URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = filename
    anchor.click()
    window.URL.revokeObjectURL(url)
}

function extractAxiosErrorMessage(error: unknown, fallback: string): string {
    if (axios.isAxiosError(error)) {
        if (error.response?.data?.error) {
            return String(error.response.data.error)
        }
        if (error.response?.data?.message) {
            return String(error.response.data.message)
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

export function useConfigBackupRestore(
    options: UseConfigBackupRestoreOptions,
) {
    const backupIncludeTradeData = ref(false)
    const backupDownloadLoading = ref(false)
    const restoreLoading = ref(false)
    const backupFileInputRef = ref<HTMLInputElement | null>(null)
    const selectedBackupFileName = ref<string | null>(null)
    const selectedBackupPayload = ref<BackupPayload | null>(null)

    const selectedBackupHasTradeData = computed(() =>
        Boolean(
            selectedBackupPayload.value &&
                typeof selectedBackupPayload.value.trade_data === 'object',
        ),
    )
    const selectedBackupConfigCount = computed(() => {
        const configRows = selectedBackupPayload.value?.config
        return Array.isArray(configRows) ? configRows.length : 0
    })

    function openBackupFilePicker(): void {
        backupFileInputRef.value?.click()
    }

    function clearSelectedBackup(): void {
        selectedBackupFileName.value = null
        selectedBackupPayload.value = null
        if (backupFileInputRef.value) {
            backupFileInputRef.value.value = ''
        }
    }

    async function handleBackupDownload(): Promise<OperationResult> {
        if (backupDownloadLoading.value) {
            return {
                status: 'noop',
                message: 'Backup download is already in progress.',
            }
        }

        backupDownloadLoading.value = true
        try {
            const response = await axios.get<BackupPayload>(
                options.apiUrl('/config/backup/export'),
                {
                    params: {
                        include_trade_data: backupIncludeTradeData.value,
                    },
                },
            )
            downloadTextFile(
                buildBackupFilename(backupIncludeTradeData.value),
                JSON.stringify(response.data, null, 2),
            )
            if (options.surfaceMessages !== false) {
                options.message.success('Backup downloaded successfully.')
            }
            return {
                status: 'success',
                message: 'Backup downloaded successfully.',
            }
        } catch (error) {
            const message = extractAxiosErrorMessage(
                error,
                'Backup download failed.',
            )
            if (options.surfaceMessages !== false) {
                options.message.error(message)
            }
            return {
                status: 'error',
                message,
            }
        } finally {
            backupDownloadLoading.value = false
        }
    }

    async function handleBackupFileSelected(event: Event): Promise<void> {
        const input = event.target as HTMLInputElement
        const selectedFile = input.files?.[0]
        if (!selectedFile) {
            return
        }

        try {
            const rawText = await selectedFile.text()
            const parsed = JSON.parse(rawText) as unknown
            if (!isBackupPayload(parsed)) {
                throw new Error('Selected file is not a valid Moonwalker backup.')
            }
            selectedBackupFileName.value = selectedFile.name
            selectedBackupPayload.value = parsed
            options.message.success(`Loaded backup ${selectedFile.name}`)
        } catch (error) {
            clearSelectedBackup()
            options.message.error(
                error instanceof Error
                    ? error.message
                    : 'Failed to read backup file.',
            )
        }
    }

    async function handleRestoreBackup(
        mode: BackupRestoreMode,
    ): Promise<OperationResult> {
        if (!selectedBackupPayload.value) {
            const message = 'Please select a backup file first.'
            if (options.surfaceMessages !== false) {
                options.message.error(message)
            }
            return {
                status: 'error',
                message,
            }
        }
        if (restoreLoading.value) {
            return {
                status: 'noop',
                message: 'Backup restore is already in progress.',
            }
        }
        if (mode === 'full' && !selectedBackupHasTradeData.value) {
            const message = 'The selected backup does not include trade data.'
            if (options.surfaceMessages !== false) {
                options.message.error(message)
            }
            return {
                status: 'error',
                message,
            }
        }

        if (
            options.hasUnsavedChanges() &&
            !window.confirm(
                'You have unsaved configuration changes. Continue and replace them with the backup?',
            )
        ) {
            return {
                status: 'noop',
                message: 'Backup restore cancelled.',
            }
        }

        const confirmationMessage =
            mode === 'full'
                ? 'Restore the full backup now? This will replace the current configuration and all trade data.'
                : 'Restore configuration only now? This will replace the current configuration.'
        if (!window.confirm(confirmationMessage)) {
            return {
                status: 'noop',
                message: 'Backup restore cancelled.',
            }
        }

        restoreLoading.value = true
        try {
            const response = await axios.post<RestoreResponse>(
                options.apiUrl('/config/backup/restore'),
                {
                    backup: selectedBackupPayload.value,
                    restore_trade_data: mode === 'full',
                },
            )

            options.onBeforeReload()
            await options.reloadConfig()

            const failedSymbols =
                response.data?.result?.history_failed_symbols ?? []
            if (Array.isArray(failedSymbols) && failedSymbols.length > 0) {
                const message = `${response.data?.message || 'Restore completed.'} History refresh failed for: ${failedSymbols.join(', ')}`
                if (options.surfaceMessages !== false) {
                    options.message.warning(message)
                }
                return {
                    status: 'success',
                    message,
                }
            } else {
                const message =
                    response.data?.message || 'Restore completed successfully.'
                if (options.surfaceMessages !== false) {
                    options.message.success(message)
                }
                return {
                    status: 'success',
                    message,
                }
            }
        } catch (error) {
            const message = extractAxiosErrorMessage(
                error,
                'Backup restore failed.',
            )
            if (options.surfaceMessages !== false) {
                options.message.error(message)
            }
            return {
                status: 'error',
                message,
            }
        } finally {
            restoreLoading.value = false
        }
    }

    return {
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
    }
}
