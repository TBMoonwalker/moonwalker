<script setup lang="ts">
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

            <input
                :ref="bindBackupFileInput"
                type="file"
                accept="application/json,.json"
                class="backup-file-input"
                @change="emit('backup-file-selected', $event)"
            >

            <n-flex align="center" :wrap="true" :size="[12, 12]">
                <n-button secondary @click="emit('open-backup-file-picker')">
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
                    type="warning"
                    :loading="restoreLoading"
                    :disabled="!hasSelectedBackupPayload"
                    @click="emit('restore-backup', 'config')"
                >
                    Restore config only
                </n-button>
                <n-button
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

.backup-file-input {
    display: none;
}

.backup-file-name {
    font-size: 14px;
}
</style>
