<script setup lang="ts">
import { RouterLink } from 'vue-router'
import type { RestoreReviewState } from '../../composables/useConfigBackupRestore'
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
    restoreReview: RestoreReviewState | null
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
    <section
        :ref="bindBackupRestoreTargetRef"
        class="utility-group"
        id="control-center-backup-restore"
    >
        <header class="utility-group-heading" tabindex="-1" data-control-center-anchor>
            <h2>{{ backupRestoreTitle }}</h2>
            <p>{{ backupRestoreSummary }}</p>
        </header>

        <div class="utility-grid">
            <section class="utility-card dashboard-panel" aria-labelledby="download-backup-title">
                <div class="utility-card-copy">
                    <h3 id="download-backup-title">Download a backup</h3>
                    <p>Save the current configuration. Include trade data when you need a full snapshot.</p>
                </div>
                <ConfigBackupDownloadControls
                    action-button-class="utility-action-button"
                    :backup-download-loading="backupDownloadLoading"
                    :backup-include-trade-data="backupIncludeTradeData"
                    :download-button-secondary="false"
                    :download-button-strong="true"
                    info-title="Portable backup"
                    info-message="Download the current configuration or include trade data."
                    :show-info="false"
                    @download-backup="emit('download-backup')"
                    @update:backup-include-trade-data="emit('update:backup-include-trade-data', $event)"
                />
            </section>

            <section class="utility-card dashboard-panel" aria-labelledby="restore-backup-title">
                <div class="utility-card-copy">
                    <h3 id="restore-backup-title">Restore a backup</h3>
                    <p>Select a JSON backup to review before restoring saved settings or trade data.</p>
                </div>
                <ConfigBackupRestoreControls
                    action-button-class="utility-action-button"
                    :bind-backup-file-input="bindBackupFileInput"
                    :has-selected-backup-payload="hasSelectedBackupPayload"
                    :restore-loading="restoreLoading"
                    :restore-review="restoreReview"
                    :selected-backup-config-count="selectedBackupConfigCount"
                    :selected-backup-file-name="selectedBackupFileName"
                    :selected-backup-has-trade-data="selectedBackupHasTradeData"
                    @backup-file-selected="emit('backup-file-selected', $event)"
                    @clear-selected-backup="emit('clear-selected-backup')"
                    @open-backup-file-picker="emit('open-backup-file-picker')"
                    @restore-backup="emit('restore-backup', $event)"
                />
            </section>
        </div>
    </section>

    <section class="utility-card utility-connectivity dashboard-panel" aria-labelledby="connectivity-title">
        <div class="utility-card-copy">
            <h2 id="connectivity-title">Test Telegram delivery</h2>
            <p>Send a test message using the saved operator alert settings.</p>
        </div>
        <div class="connectivity-actions">
            <n-button
                class="utility-action-button"
                type="primary"
                secondary
                :loading="monitoringTestLoading"
                :disabled="!canTestMonitoringTelegram"
                @click="emit('monitoring-test')"
            >
                Send test message
            </n-button>
            <span v-if="canTestMonitoringTelegram" class="utility-help">
                Saved Telegram credentials are ready.
            </span>
            <RouterLink
                v-else
                class="utility-link"
                :to="{ name: 'controlCenter', query: { mode: 'setup', target: 'monitoring' } }"
            >
                Configure operator alerts ↗
            </RouterLink>
        </div>
    </section>
</template>

<style scoped>
.utility-group {
    width: 100%;
    display: flex;
    flex-direction: column;
    gap: 12px;
}

.utility-group-heading {
    display: grid;
    gap: 4px;
}

.utility-group-heading:focus,
.utility-group-heading:focus-visible {
    outline: var(--mw-focus-ring);
    outline-offset: var(--mw-focus-offset);
}

.utility-group-heading h2 {
    margin: 0;
    color: var(--mw-color-text-primary);
    font-family: var(--mw-font-display);
    font-size: 1.15rem;
    font-weight: 600;
    letter-spacing: -0.02em;
}

.utility-group-heading p,
.utility-card-copy p {
    margin: 0;
    color: var(--mw-color-text-secondary);
    font-size: 0.875rem;
    line-height: 1.5;
}

.utility-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 14px;
}

.utility-card {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 18px;
    padding: 20px;
}

.utility-card-copy {
    display: grid;
    gap: 6px;
}

.utility-card-copy h2,
.utility-card-copy h3 {
    margin: 0;
    font-family: var(--mw-font-display);
    font-size: 1.05rem;
    font-weight: 600;
    line-height: 1.25;
}

.utility-card :deep(.backup-download-actions),
.utility-card :deep(.backup-restore-actions),
.utility-card :deep(.backup-picker) {
    width: 100%;
}

.utility-card :deep(.backup-restore-actions) {
    margin-top: auto;
}

.utility-connectivity {
    width: 100%;
}

.connectivity-actions {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 10px 14px;
}

.utility-help,
.utility-link {
    color: var(--mw-color-text-secondary);
    font-size: 0.875rem;
}

.utility-link {
    color: var(--mw-color-primary-strong);
    text-decoration: none;
}

.utility-link:hover,
.utility-link:focus-visible {
    text-decoration: underline;
}

@media (max-width: 850px) {
    .utility-grid { grid-template-columns: 1fr; }
}

@media (max-width: 560px) {
    .utility-card { padding: 18px; }
    .utility-card :deep(.backup-download-actions),
    .utility-card :deep(.backup-restore-actions),
    .utility-card :deep(.backup-picker),
    .connectivity-actions {
        align-items: stretch;
        flex-direction: column;
    }
    .utility-card :deep(.utility-action-button) {
        width: 100%;
        min-height: 44px;
    }
    .utility-connectivity :deep(.utility-action-button) {
        min-height: 44px;
    }
}
</style>
