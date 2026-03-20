<template>
    <n-card title="Messaging / Monitoring settings">
        <n-form
            ref="formRef"
            :model="monitoring"
            :rules="rules"
            label-width="auto"
            require-mark-placement="right-hanging"
            :style="{
                maxWidth: '640px',
            }"
        >
            <n-form-item label="Enabled" path="monitoring_enabled" label-placement="left">
                <n-checkbox v-model:checked="monitoring.enabled" />
            </n-form-item>
            <n-form-item label="Telegram Bot Token" path="monitoring_telegram_bot_token">
                <n-input
                    v-model:value="monitoring.telegram_bot_token"
                    type="password"
                    show-password-on="click"
                    placeholder="123456:ABC-DEF..."
                />
            </n-form-item>
            <n-form-item label="Telegram API ID" path="monitoring_telegram_api_id">
                <n-input-number
                    v-model:value="monitoring.telegram_api_id"
                    placeholder="1234567"
                />
            </n-form-item>
            <n-form-item label="Telegram API Hash" path="monitoring_telegram_api_hash">
                <n-input
                    v-model:value="monitoring.telegram_api_hash"
                    type="password"
                    show-password-on="click"
                    placeholder="0123456789abcdef0123456789abcdef"
                />
            </n-form-item>
            <n-form-item label="Telegram Chat ID" path="monitoring_telegram_chat_id">
                <n-input
                    v-model:value="monitoring.telegram_chat_id"
                    placeholder="e.g. 123456789 or -100123..."
                />
            </n-form-item>
            <n-form-item label="Timeout (seconds)" path="monitoring_timeout_sec">
                <n-input-number
                    v-model:value="monitoring.timeout_sec"
                    placeholder="5"
                />
            </n-form-item>
            <n-form-item label="Retry count" path="monitoring_retry_count">
                <n-input-number
                    v-model:value="monitoring.retry_count"
                    placeholder="1"
                />
            </n-form-item>
            <n-form-item v-if="showTestAction" label="Telegram connectivity">
                <n-button
                    secondary
                    type="primary"
                    :loading="testLoading"
                    :disabled="!canTest"
                    @click="onTest"
                >
                    Test Telegram
                </n-button>
            </n-form-item>
        </n-form>
    </n-card>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import type { FormInst, FormRules } from 'naive-ui/es/form'

interface MonitoringModel {
    enabled: boolean
    telegram_bot_token: string | null
    telegram_api_id: number | null
    telegram_api_hash: string | null
    telegram_chat_id: string | null
    timeout_sec: number
    retry_count: number
}

withDefaults(defineProps<{
    canTest: boolean
    monitoring: MonitoringModel
    onTest: () => void
    rules: FormRules
    showTestAction?: boolean
    testLoading: boolean
}>(), {
    showTestAction: true,
})

const formRef = ref<FormInst | null>(null)

async function validate(): Promise<boolean> {
    if (!formRef.value) {
        return true
    }
    return await new Promise<boolean>((resolve) => {
        formRef.value?.validate((errors) => resolve(!errors))
    })
}

defineExpose({
    validate,
})
</script>
