<script setup lang="ts">
import ConfigBackupDownloadControls from '../config/ConfigBackupDownloadControls.vue'
import ConfigBackupRestoreControls from '../config/ConfigBackupRestoreControls.vue'

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
        <n-card title="Backup & Restore" size="small" class="mw-shell-card">
            <n-flex vertical :size="12">
                <ConfigBackupDownloadControls
                    action-button-class="utility-action-button"
                    :backup-download-loading="backupDownloadLoading"
                    :backup-include-trade-data="backupIncludeTradeData"
                    :download-button-secondary="false"
                    :download-button-strong="true"
                    info-title="Portable backup"
                    info-message="Download configuration alone or include all trade data. Full restores will repopulate the shared workspace after the backend finishes."
                    @download-backup="emit('download-backup')"
                    @update:backup-include-trade-data="emit('update:backup-include-trade-data', $event)"
                />

                <n-divider />

                <ConfigBackupRestoreControls
                    action-button-class="utility-action-button"
                    :bind-backup-file-input="bindBackupFileInput"
                    :has-selected-backup-payload="hasSelectedBackupPayload"
                    :restore-loading="restoreLoading"
                    :selected-backup-config-count="selectedBackupConfigCount"
                    :selected-backup-file-name="selectedBackupFileName"
                    :selected-backup-has-trade-data="selectedBackupHasTradeData"
                    @backup-file-selected="emit('backup-file-selected', $event)"
                    @clear-selected-backup="emit('clear-selected-backup')"
                    @open-backup-file-picker="emit('open-backup-file-picker')"
                    @restore-backup="emit('restore-backup', $event)"
                />
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
        <n-card size="small" class="mw-shell-card">
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

</style>
