<script setup lang="ts">
import ConfigBackupRestoreControls from '../config/ConfigBackupRestoreControls.vue'
import type { SetupEntryChoice } from '../../control-center/setupEntryHistory'

type BackupRestoreMode = 'config' | 'full'

defineProps<{
    bindBackupFileInput: (element: Element | null) => void
    hasSelectedBackupPayload: boolean
    restoreLoading: boolean
    selectedBackupConfigCount: number
    selectedBackupFileName: string | null
    selectedBackupHasTradeData: boolean
}>()

const emit = defineEmits<{
    'backup-file-selected': [event: Event]
    'clear-selected-backup': []
    'open-backup-file-picker': []
    'restore-backup': [mode: BackupRestoreMode]
    'select-entry-choice': [choice: SetupEntryChoice]
}>()
</script>

<template>
    <n-card
        class="workspace-card setup-flow-card"
        content-style="padding: 20px 22px;"
    >
        <n-flex vertical :size="18">
            <n-flex justify="space-between" align="center" :wrap="true">
                <div>
                    <h2 class="workspace-title">Restore and review</h2>
                    <n-text depth="3" class="workspace-summary">
                        Bring an existing Moonwalker installation forward first,
                        then land in a readiness review before making changes.
                    </n-text>
                </div>
                <n-button
                    quaternary
                    @click="emit('select-entry-choice', 'new')"
                >
                    Start a new setup instead
                </n-button>
            </n-flex>

            <n-alert type="info" title="Import first, review second">
                Restoring does not skip safety review. Moonwalker will reload the
                imported configuration and send you to a readiness check after the
                backend completes the restore.
            </n-alert>

            <ConfigBackupRestoreControls
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
</template>

<style scoped>
.workspace-title {
    color: var(--mw-color-text-primary);
    font-family: var(--mw-font-display);
    font-size: clamp(1.35rem, 2.4vw, 1.8rem);
    line-height: 1.2;
    font-weight: 700;
    letter-spacing: -0.02em;
}

.workspace-summary {
    display: block;
    margin-top: 6px;
    max-width: 68ch;
}

.setup-flow-card {
    border: 1px solid rgba(29, 92, 73, 0.14);
    background: var(--mw-surface-shell);
}
</style>
