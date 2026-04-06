<script setup lang="ts">
type BackupRestoreMode = 'config' | 'full'

defineProps<{
    backupDownloadLoading: boolean
    backupIncludeTradeData: boolean
    backupRestoreSummary: string
    backupRestoreTitle: string
    bindBackupFileInput: (element: Element | null) => void
    bindBackupRestoreTargetRef: (element: Element | null) => void
    canTestMonitoringTelegram: boolean
    hasSelectedBackupPayload: boolean
    monitoringTestLoading: boolean
    restoreLoading: boolean
    selectedBackupConfigCount: number
    selectedBackupFileName: string | null
    selectedBackupHasTradeData: boolean
}>()

const emit = defineEmits<{
    'backup-file-selected': [event: Event]
    'clear-selected-backup': []
    'download-backup': []
    'monitoring-test': []
    'open-backup-file-picker': []
    'restore-backup': [mode: BackupRestoreMode]
    'update:backup-include-trade-data': [checked: boolean]
}>()
</script>

<template>
    <div
        :ref="bindBackupRestoreTargetRef"
        class="task-section"
        id="control-center-backup-restore"
    >
        <div class="task-section-header" tabindex="-1" data-control-center-anchor>
            <h2>{{ backupRestoreTitle }}</h2>
            <n-text depth="3">{{ backupRestoreSummary }}</n-text>
        </div>
        <n-card title="Backup & Restore" size="small">
            <n-flex vertical :size="12">
                <n-alert type="info" title="Portable backup">
                    Download configuration alone or include all trade data. Full restores
                    will repopulate the shared workspace after the backend finishes.
                </n-alert>

                <n-flex align="center" :wrap="true" :size="[12, 12]">
                    <n-checkbox
                        :checked="backupIncludeTradeData"
                        @update:checked="emit('update:backup-include-trade-data', $event)"
                    >
                        Include trade data in backup
                    </n-checkbox>
                    <n-button
                        class="utility-action-button"
                        type="primary"
                        strong
                        :loading="backupDownloadLoading"
                        @click="emit('download-backup')"
                    >
                        Download backup
                    </n-button>
                </n-flex>

                <n-divider />

                <input
                    :ref="bindBackupFileInput"
                    type="file"
                    accept="application/json,.json"
                    class="backup-file-input"
                    @change="emit('backup-file-selected', $event)"
                >

                <n-flex align="center" :wrap="true" :size="[12, 12]">
                    <n-button
                        class="utility-action-button"
                        secondary
                        @click="emit('open-backup-file-picker')"
                    >
                        Select backup file
                    </n-button>
                    <span v-if="selectedBackupFileName" class="backup-file-name">
                        {{ selectedBackupFileName }}
                    </span>
                    <n-button
                        v-if="selectedBackupFileName"
                        quaternary
                        @click="emit('clear-selected-backup')"
                    >
                        Clear
                    </n-button>
                </n-flex>

                <n-text v-if="hasSelectedBackupPayload" depth="3">
                    Loaded backup with {{ selectedBackupConfigCount }} config keys<span v-if="selectedBackupHasTradeData"> and trade data</span>.
                </n-text>

                <n-flex align="center" :wrap="true" :size="[12, 12]">
                    <n-button
                        class="utility-action-button"
                        type="warning"
                        :loading="restoreLoading"
                        :disabled="!hasSelectedBackupPayload"
                        @click="emit('restore-backup', 'config')"
                    >
                        Restore config only
                    </n-button>
                    <n-button
                        class="utility-action-button"
                        type="error"
                        ghost
                        :loading="restoreLoading"
                        :disabled="!selectedBackupHasTradeData"
                        @click="emit('restore-backup', 'full')"
                    >
                        Restore full backup
                    </n-button>
                </n-flex>
            </n-flex>
        </n-card>
    </div>

    <div class="task-section">
        <div class="task-section-header">
            <h2>Connectivity test</h2>
            <n-text depth="3">
                Run operational utility checks without mixing them into the config draft.
            </n-text>
        </div>
        <n-card size="small">
            <n-flex vertical :size="12">
                <n-text depth="3">
                    Send a Telegram test using the currently saved monitoring configuration.
                </n-text>
                <n-flex align="center" :wrap="true" :size="[12, 12]">
                    <n-button
                        class="utility-action-button"
                        secondary
                        type="primary"
                        :loading="monitoringTestLoading"
                        :disabled="!canTestMonitoringTelegram"
                        @click="emit('monitoring-test')"
                    >
                        Test Telegram
                    </n-button>
                    <n-text depth="3">
                        {{
                            canTestMonitoringTelegram
                                ? 'Saved monitoring credentials are ready for a test message.'
                                : 'Complete Telegram credentials in Setup first.'
                        }}
                    </n-text>
                </n-flex>
            </n-flex>
        </n-card>
    </div>
</template>

<style scoped>
.task-section {
    width: 100%;
    display: flex;
    flex-direction: column;
    gap: 10px;
}

.task-section-header {
    display: flex;
    flex-direction: column;
    gap: 4px;
}

.task-section-header:focus,
.task-section-header:focus-visible {
    outline: none;
    box-shadow: none;
}

.task-section-header h2 {
    color: var(--mw-color-text-primary);
    font-family: var(--mw-font-display);
    font-size: 1.05rem;
    font-weight: 700;
    letter-spacing: -0.01em;
}

.backup-file-input {
    display: none;
}

.backup-file-name {
    font-size: 14px;
}
</style>
