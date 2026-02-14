<template>
    <n-flex vertical :size="12">
        <input ref="csvInputRef" type="file" accept=".csv,text/csv" style="display: none;" @change="handleCsvFileChange" />
        <n-flex align="center" :size="8">
            <n-button type="primary" ghost @click="openFilePicker">
                Choose CSV
            </n-button>
            <span>{{ selectedFileName }}</span>
        </n-flex>
        <n-flex align="center" :size="8">
            <n-icon size="18" color="#d03050">
                <WarningOutline />
            </n-icon>
            <n-checkbox v-model:checked="overwriteExisting">
                Overwrite existing symbols
            </n-checkbox>
        </n-flex>
        <n-text v-if="overwriteExisting" type="error">
            Danger: when enabled, existing open entries for imported symbols are replaced.
        </n-text>
        <n-button type="primary" :disabled="!selectedFile || uploadInProgress" :loading="uploadInProgress"
            @click="handleCsvImport">
            Import CSV
        </n-button>
    </n-flex>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { NButton, NCheckbox, NFlex, NIcon, NText, useMessage } from 'naive-ui'
import { WarningOutline } from '@vicons/ionicons5'
import { fetchJson } from '../api/client'

const message = useMessage()
const csvInputRef = ref<HTMLInputElement | null>(null)
const selectedFile = ref<File | null>(null)
const overwriteExisting = ref(false)
const uploadInProgress = ref(false)
const selectedFileName = ref('No file selected')

function openFilePicker(): void {
    csvInputRef.value?.click()
}

function handleCsvFileChange(event: Event): void {
    const target = event.target as HTMLInputElement
    selectedFile.value = target.files?.[0] ?? null
    selectedFileName.value = selectedFile.value?.name ?? 'No file selected'
}

type CsvImportResponse = {
    result: string
    error?: string
    row_count?: number
    symbol_count?: number
}

async function handleCsvImport(): Promise<void> {
    if (!selectedFile.value) {
        message.error('Please select a CSV file first.')
        return
    }

    uploadInProgress.value = true
    try {
        const formData = new FormData()
        formData.append('file', selectedFile.value)
        formData.append('overwrite', overwriteExisting.value ? 'true' : 'false')

        const result = await fetchJson<CsvImportResponse>('/trades/import/csv', {
            method: 'POST',
            body: formData,
        })

        if (result.result === 'ok') {
            const rowCount = result.row_count ?? 0
            const symbolCount = result.symbol_count ?? 0
            message.success(`Imported ${rowCount} row(s) for ${symbolCount} symbol(s).`)
            selectedFile.value = null
            selectedFileName.value = 'No file selected'
            if (csvInputRef.value) {
                csvInputRef.value.value = ''
            }
            return
        }

        message.error(result.error ?? 'Import failed.')
    } catch (error) {
        const detail = error instanceof Error ? error.message : 'Unknown error'
        message.error(`Import failed: ${detail}`)
    } finally {
        uploadInProgress.value = false
    }
}
</script>
