import axios from 'axios'
import { computed, ref, shallowRef } from 'vue'

import type { OperationResult } from '../control-center/operationResults'
import { extractApiErrorMessage } from '../helpers/apiErrors'

export type BackupRestoreMode = 'config' | 'full'

type BackupPayload = {
    config?: unknown
    trade_data?: unknown
    includes_trade_data?: boolean
}

export type ClassificationSeverity = 'info' | 'warning' | 'blocking'

export interface ClassificationFinding {
    code: string
    severity: ClassificationSeverity
    message: string
    nextAction: string | null
}

export interface BackupClassification {
    mode: BackupRestoreMode
    schemaVersion: number | null
    tradeModeEra: 'accumulation' | 'dynamic_dca' | 'legacy_unspecified' | null
    includesAccumulation: boolean
    findings: ClassificationFinding[]
    blocking: boolean
}

type ClassifyResponse = {
    classification?: {
        schema_version?: number | null
        trade_mode_era?: string | null
        includes_accumulation?: boolean
    }
    findings?: Array<{
        code?: string
        severity?: string
        message?: string
        next_action?: string | null
    }>
}

function isKnownSeverity(value: unknown): value is ClassificationSeverity {
    return value === 'info' || value === 'warning' || value === 'blocking'
}

function toFinding(raw: NonNullable<ClassifyResponse['findings']>[number]): ClassificationFinding {
    return {
        code: String(raw.code || 'unknown'),
        severity: isKnownSeverity(raw.severity) ? raw.severity : 'warning',
        message: String(raw.message || 'Backup review finding.'),
        nextAction: raw.next_action != null ? String(raw.next_action) : null,
    }
}

function toClassification(
    mode: BackupRestoreMode,
    payload: unknown,
): BackupClassification {
    if (typeof payload !== 'object' || payload === null || Array.isArray(payload)) {
        throw new Error('Invalid backup review response.')
    }
    const response = payload as ClassifyResponse
    if (
        typeof response.classification !== 'object' ||
        response.classification === null ||
        Array.isArray(response.classification) ||
        !(response.classification.schema_version === null ||
            (typeof response.classification.schema_version === 'number' &&
                Number.isInteger(response.classification.schema_version))) ||
        ![null, 'accumulation', 'dynamic_dca', 'legacy_unspecified'].includes(
            response.classification.trade_mode_era ?? null,
        ) ||
        typeof response.classification.includes_accumulation !== 'boolean' ||
        !Array.isArray(response.findings) ||
        response.findings.some(finding =>
            typeof finding !== 'object' || finding === null ||
            !isKnownSeverity(finding.severity) ||
            typeof finding.code !== 'string' || !finding.code ||
            typeof finding.message !== 'string' || !finding.message ||
            (finding.next_action != null && typeof finding.next_action !== 'string'),
        )
    ) {
        throw new Error('Invalid backup review response.')
    }
    const findings = response.findings.map(toFinding)
    return {
        mode,
        schemaVersion:
            typeof response.classification?.schema_version === 'number'
                ? response.classification.schema_version
                : null,
        tradeModeEra:
            response.classification?.trade_mode_era === 'accumulation' ||
            response.classification?.trade_mode_era === 'dynamic_dca' ||
            response.classification?.trade_mode_era === 'legacy_unspecified'
                ? response.classification.trade_mode_era
                : null,
        includesAccumulation: Boolean(response.classification?.includes_accumulation),
        findings,
        blocking: findings.some(finding => finding.severity === 'blocking'),
    }
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

type RestoreMigrationError = {
    code?: string
    message?: string
    next_action?: string
    safe_fields?: Record<string, unknown>
}

type RestoreErrorResponse = {
    error?: string
    message?: string
    migration_error?: RestoreMigrationError
}

export interface RestoreReviewState {
    code: string
    message: string
    nextAction: string | null
    previewMessage?: string
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

function buildRestoreReview(error: unknown): RestoreReviewState | null {
    if (!axios.isAxiosError<RestoreErrorResponse>(error)) {
        return null
    }
    const payload = error.response?.data?.migration_error
    if (!payload || typeof payload !== 'object') {
        return null
    }
    const message = String(
        payload.message ||
            error.response?.data?.message ||
            error.response?.data?.error ||
            'Restore review required.',
    )
    return {
        code: String(payload.code || 'restore_review'),
        message,
        nextAction:
            payload.next_action != null
                ? String(payload.next_action)
                : null,
    }
}

export function useConfigBackupRestore(
    options: UseConfigBackupRestoreOptions,
) {
    const backupIncludeTradeData = ref(false)
    const backupDownloadLoading = ref(false)
    const restoreLoading = ref(false)
    const backupFileInputRef = shallowRef<HTMLInputElement | null>(null)
    const selectedBackupFileName = ref<string | null>(null)
    const selectedBackupPayload = ref<BackupPayload | null>(null)
    const restoreReview = ref<RestoreReviewState | null>(null)
    const backupClassifications = ref<Partial<Record<BackupRestoreMode, BackupClassification>>>({})
    const classificationLoading = ref(false)

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

    function bindBackupFileInput(element: Element | import('vue').ComponentPublicInstance | null): void {
        backupFileInputRef.value =
            typeof HTMLInputElement !== 'undefined' &&
            element instanceof HTMLInputElement
                ? element
                : null
    }

    let backupSelectionGeneration = 0
    const previewFailures = new Set<BackupRestoreMode>()

    function previewFailureMessage(): string {
        const scopes = Array.from(previewFailures)
            .map(scope => scope === 'full' ? 'full backup' : 'config only')
            .join(' and ')
        return `Backup review is unavailable for ${scopes}. Restore is blocked until that review succeeds.`
    }

    function updatePreviewFailure(mode: BackupRestoreMode, failed: boolean): void {
        if (failed) previewFailures.add(mode)
        else previewFailures.delete(mode)
        if (previewFailures.size > 0) {
            const message = previewFailureMessage()
            restoreReview.value = restoreReview.value && restoreReview.value.code !== 'preview_unavailable'
                ? { ...restoreReview.value, previewMessage: message }
                : { code: 'preview_unavailable', message, nextAction: 'Retry the restore to review the backup again.' }
        } else if (restoreReview.value?.code === 'preview_unavailable') {
            restoreReview.value = null
        } else if (restoreReview.value?.previewMessage) {
            const { previewMessage: _previewMessage, ...review } = restoreReview.value
            restoreReview.value = review
        }
    }

    function clearSelectedBackup(): void {
        backupSelectionGeneration += 1
        previewFailures.clear()
        selectedBackupFileName.value = null
        selectedBackupPayload.value = null
        restoreReview.value = null
        backupClassifications.value = {}
        classificationLoading.value = false
        if (backupFileInputRef.value) {
            backupFileInputRef.value.value = ''
        }
    }

    const classificationInFlight = new Map<BackupRestoreMode, { generation: number; request: Promise<boolean> }>()

    async function ensureClassification(mode: BackupRestoreMode): Promise<boolean> {
        const cached = backupClassifications.value[mode]
        if (cached) {
            return !cached.blocking
        }
        const inFlight = classificationInFlight.get(mode)
        if (inFlight?.generation === backupSelectionGeneration) {
            return inFlight.request
        }
        if (!selectedBackupPayload.value) {
            return false
        }
        const generation = backupSelectionGeneration
        const payload = selectedBackupPayload.value
        const request = (async (): Promise<boolean> => {
            classificationLoading.value = true
            try {
                const response = await axios.post<ClassifyResponse>(
                    options.apiUrl('/config/backup/classify'),
                    {
                        backup: payload,
                        restore_trade_data: mode === 'full',
                    },
                )
                if (generation !== backupSelectionGeneration) return false
                const classification = toClassification(
                    mode,
                    response.data ?? {},
                )
                backupClassifications.value = {
                    ...backupClassifications.value,
                    [mode]: classification,
                }
                updatePreviewFailure(mode, false)
                return !classification.blocking
            } catch (error) {
                if (generation !== backupSelectionGeneration) return false
                updatePreviewFailure(mode, true)
                if (options.surfaceMessages !== false) {
                    options.message.warning(
                        extractApiErrorMessage(
                            error,
                            'Backup review is unavailable; retry before restoring.',
                        ),
                    )
                }
                return false
            } finally {
                if (generation === backupSelectionGeneration) classificationLoading.value = false
            }
        })()
        classificationInFlight.set(mode, { generation, request })
        try {
            return await request
        } finally {
            if (classificationInFlight.get(mode)?.request === request) classificationInFlight.delete(mode)
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
            const message = extractApiErrorMessage(
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

        const generation = ++backupSelectionGeneration
        previewFailures.clear()
        selectedBackupFileName.value = null
        selectedBackupPayload.value = null
        restoreReview.value = null
        backupClassifications.value = {}
        classificationLoading.value = false

        try {
            const rawText = await selectedFile.text()
            if (generation !== backupSelectionGeneration) return
            const parsed = JSON.parse(rawText) as unknown
            if (!isBackupPayload(parsed)) {
                throw new Error('Selected file is not a valid Moonwalker backup.')
            }
            selectedBackupFileName.value = selectedFile.name
            selectedBackupPayload.value = parsed
            restoreReview.value = null
            backupClassifications.value = {}
            options.message.success(`Loaded backup ${selectedFile.name}`)
            // Preview both restore scopes up front so the review findings are
            // visible before any restore is attempted. Sequential keeps the
            // classify call order deterministic and the loading flag accurate.
            await ensureClassification('config')
            if (generation !== backupSelectionGeneration) return
            if (selectedBackupHasTradeData.value) {
                await ensureClassification('full')
            }
        } catch (error) {
            if (generation !== backupSelectionGeneration) return
            clearSelectedBackup()
            options.message.error(
                error instanceof Error
                    ? error.message
                    : 'Failed to read backup file.',
            )
        }
    }

    async function performRestoreBackup(
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

        const generation = backupSelectionGeneration
        const payload = selectedBackupPayload.value
        // Safety net: pre-classification runs on file selection, but a
        // blocked or unavailable preview must not wedge the restore.
        const classificationAllowed = await ensureClassification(mode)
        if (generation !== backupSelectionGeneration) {
            return { status: 'noop', message: 'Backup selection changed. Review it before restoring.' }
        }
        if (!classificationAllowed) {
            return {
                status: 'blocked',
                message: 'Backup review blocked this restore.',
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

        if (restoreReview.value?.code !== 'preview_unavailable') {
            restoreReview.value = null
            if (previewFailures.size > 0) updatePreviewFailure(mode, false)
        }
        try {
            const response = await axios.post<RestoreResponse>(
                options.apiUrl('/config/backup/restore'),
                {
                    backup: payload,
                    restore_trade_data: mode === 'full',
                    confirm: true,
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
            const review = buildRestoreReview(error)
            if (review) {
                restoreReview.value = previewFailures.size > 0
                    ? { ...review, previewMessage: previewFailureMessage() }
                    : review
            } else if (previewFailures.size === 0) restoreReview.value = null
            const message = extractApiErrorMessage(
                error,
                'Backup restore failed.',
            )
            if (options.surfaceMessages !== false) {
                options.message.error(message)
            }
            return {
                status: review ? 'blocked' : 'error',
                message,
            }
        }
    }

    async function handleRestoreBackup(mode: BackupRestoreMode): Promise<OperationResult> {
        if (restoreLoading.value) {
            return { status: 'noop', message: 'Backup restore is already in progress.' }
        }
        restoreLoading.value = true
        try {
            return await performRestoreBackup(mode)
        } finally {
            restoreLoading.value = false
        }
    }

    return {
        backupClassifications,
        backupDownloadLoading,
        backupFileInputRef,
        backupIncludeTradeData,
        bindBackupFileInput,
        classificationLoading,
        clearSelectedBackup,
        handleBackupDownload,
        handleBackupFileSelected,
        handleRestoreBackup,
        openBackupFilePicker,
        restoreReview,
        restoreLoading,
        selectedBackupConfigCount,
        selectedBackupFileName,
        selectedBackupHasTradeData,
        selectedBackupPayload,
    }
}
