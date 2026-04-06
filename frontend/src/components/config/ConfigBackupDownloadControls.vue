<script setup lang="ts">
withDefaults(
    defineProps<{
        actionButtonClass?: string | null
        backupDownloadLoading: boolean
        backupIncludeTradeData: boolean
        downloadButtonSecondary?: boolean
        downloadButtonStrong?: boolean
        infoMessage: string
        infoTitle: string
    }>(),
    {
        actionButtonClass: null,
        downloadButtonSecondary: true,
        downloadButtonStrong: false,
    },
)

const emit = defineEmits<{
    'download-backup': []
    'update:backup-include-trade-data': [checked: boolean]
}>()
</script>

<template>
    <n-alert type="info" :title="infoTitle">
        {{ infoMessage }}
    </n-alert>

    <n-flex align="center" :wrap="true" :size="[12, 12]">
        <n-checkbox
            :checked="backupIncludeTradeData"
            @update:checked="emit('update:backup-include-trade-data', $event)"
        >
            Include trade data in backup
        </n-checkbox>
        <n-button
            :class="actionButtonClass || undefined"
            type="primary"
            :secondary="downloadButtonSecondary"
            :strong="downloadButtonStrong"
            :loading="backupDownloadLoading"
            @click="emit('download-backup')"
        >
            Download backup
        </n-button>
    </n-flex>
</template>
