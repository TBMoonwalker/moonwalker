<script setup lang="ts">
import type {
    BackupClassification,
    BackupRestoreMode,
    ClassificationFinding,
    RestoreReviewState,
} from '../../composables/useConfigBackupRestore'

const props = withDefaults(
    defineProps<{
        actionButtonClass?: string | null
        backupClassification?: BackupClassification | null
        backupClassifications?: Partial<Record<BackupRestoreMode, BackupClassification>>
        bindBackupFileInput: (element: Element | import('vue').ComponentPublicInstance | null) => void
        classificationLoading?: boolean
        hasSelectedBackupPayload: boolean
        restoreLoading: boolean
        restoreReview?: RestoreReviewState | null
        selectedBackupConfigCount: number
        selectedBackupFileName: string | null
        selectedBackupHasTradeData: boolean
    }>(),
    {
        actionButtonClass: null,
        backupClassification: null,
        backupClassifications: () => ({}),
        classificationLoading: false,
        restoreReview: null,
    },
)

const emit = defineEmits<{
    'backup-file-selected': [event: Event]
    'clear-selected-backup': []
    'open-backup-file-picker': []
    'restore-backup': [mode: BackupRestoreMode]
}>()

function isBlocking(mode: BackupRestoreMode): boolean {
    return props.backupClassifications?.[mode]?.blocking ?? false
}

function findingLabel(finding: ClassificationFinding): string {
    return finding.severity === 'blocking' ? 'Blocking' : 'Warning'
}
</script>

<template>
    <input
        :ref="bindBackupFileInput"
        type="file"
        accept="application/json,.json"
        class="backup-file-input"
        @change="emit('backup-file-selected', $event)"
    >

    <n-flex class="backup-picker" align="center" :wrap="true" :size="[12, 12]">
        <n-button
            :class="actionButtonClass || undefined"
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

    <div
        v-if="backupClassification || classificationLoading"
        class="backup-classification"
        role="status"
        aria-live="polite"
    >
        <n-text v-if="classificationLoading && !backupClassification" depth="3">
            Reviewing backup…
        </n-text>
        <n-alert
            v-else-if="backupClassification"
            :type="backupClassification.blocking ? 'error' : 'info'"
            :bordered="false"
            :title="`Backup review (${backupClassification.mode === 'full' ? 'full backup' : 'config only'} restore)`"
        >
            <ul class="backup-classification-findings">
                <li
                    v-for="finding in backupClassification.findings"
                    :key="`${finding.code}:${finding.message}`"
                >
                    <n-text :depth="finding.severity === 'info' ? 3 : 2">
                        <template v-if="finding.severity !== 'info'">
                            [{{ findingLabel(finding) }}]
                        </template>
                        {{ finding.message }}
                    </n-text>
                    <div v-if="finding.nextAction" class="restore-review-next-action">
                        {{ finding.nextAction }}
                    </div>
                </li>
            </ul>
        </n-alert>
    </div>

    <n-alert
        v-if="restoreReview"
        type="warning"
        :bordered="false"
        :title="`Restore review: ${restoreReview.code}`"
    >
        <div>{{ restoreReview.message }}</div>
        <div v-if="restoreReview.nextAction" class="restore-review-next-action">
            {{ restoreReview.nextAction }}
        </div>
    </n-alert>

    <n-flex class="backup-restore-actions" align="center" :wrap="true" :size="[12, 12]">
        <n-button
            :class="actionButtonClass || undefined"
            type="warning"
            :loading="restoreLoading || classificationLoading"
            :disabled="!hasSelectedBackupPayload || isBlocking('config')"
            @click="emit('restore-backup', 'config')"
        >
            Restore config only
        </n-button>
        <n-button
            :class="actionButtonClass || undefined"
            type="error"
            ghost
            :loading="restoreLoading || classificationLoading"
            :disabled="!selectedBackupHasTradeData || isBlocking('full')"
            @click="emit('restore-backup', 'full')"
        >
            Restore full backup
        </n-button>
    </n-flex>
</template>

<style scoped>
.backup-file-input {
    display: none;
}

.backup-file-name {
    font-size: 14px;
}

.backup-classification-findings {
    margin: 0;
    padding-left: 18px;
    display: flex;
    flex-direction: column;
    gap: 6px;
}

.restore-review-next-action {
    margin-top: 6px;
}
</style>
