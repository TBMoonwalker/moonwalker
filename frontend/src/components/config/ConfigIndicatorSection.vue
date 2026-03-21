<template>
    <n-card :title="cardTitle === null ? undefined : cardTitle ?? 'Indicator settings'">
        <n-form
            ref="formRef"
            :model="indicator"
            :rules="rules"
            label-width="auto"
            require-mark-placement="right-hanging"
            :style="{
                maxWidth: '640px',
            }"
        >
            <n-form-item
                label="UPNL history retention (days, 0 = infinite)"
                path="upnl_housekeeping_interval"
            >
                <n-input-number
                    v-model:value="indicator.upnl_housekeeping_interval"
                    placeholder="UPNL retention"
                />
            </n-form-item>
            <n-form-item label="History Lookback Time" path="history_lookback_time">
                <n-select
                    v-model:value="indicator.history_lookback_time"
                    :options="historyLookbackOptions"
                    filterable
                    tag
                    placeholder="e.g. 90d, 1y"
                />
            </n-form-item>
        </n-form>
    </n-card>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import type { FormInst, FormRules } from 'naive-ui/es/form'

interface SelectOption {
    label: string
    value: string
}

interface IndicatorModel {
    upnl_housekeeping_interval: number
    history_lookback_time: string | null
}

defineProps<{
    historyLookbackOptions: SelectOption[]
    indicator: IndicatorModel
    rules: FormRules
    cardTitle?: string | null
}>()

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
