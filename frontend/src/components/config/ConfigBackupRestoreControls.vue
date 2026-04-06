<script setup lang="ts">
type BackupRestoreMode = 'config' | 'full'

withDefaults(
    defineProps<{
        actionButtonClass?: string | null
        bindBackupFileInput: (element: Element | null) => void
        hasSelectedBackupPayload: boolean
        restoreLoading: boolean
        selectedBackupConfigCount: number
        selectedBackupFileName: string | null
        selectedBackupHasTradeData: boolean
    }>(),
    {
        actionButtonClass: null,
    },
)

const emit = defineEmits<{
    'backup-file-selected': [event: Event]
    'clear-selected-backup': []
    'open-backup-file-picker': []
    'restore-backup': [mode: BackupRestoreMode]
}>()
</script>

<template>
    <input
        :ref="bindBackupFileInput"
        type="file"
        accept="application/json,.json"
        class="backup-file-input"
        @change="emit('backup-file-selected', $event)"
    >

    <n-flex align="center" :wrap="true" :size="[12, 12]">
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

    <n-flex align="center" :wrap="true" :size="[12, 12]">
        <n-button
            :class="actionButtonClass || undefined"
            type="warning"
            :loading="restoreLoading"
            :disabled="!hasSelectedBackupPayload"
            @click="emit('restore-backup', 'config')"
        >
            Restore config only
        </n-button>
        <n-button
            :class="actionButtonClass || undefined"
            type="error"
            ghost
            :loading="restoreLoading"
            :disabled="!selectedBackupHasTradeData"
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
</style>
