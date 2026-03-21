<template>
    <n-card>
        <n-form
            ref="formRef"
            :model="exchange"
            :rules="rules"
            label-width="auto"
            require-mark-placement="right-hanging"
            :style="{
                maxWidth: '640px',
            }"
        >
            <n-form-item label="Exchange Hostname" path="exchange_hostname">
                <n-input
                    v-model:value="exchange.exchange_hostname"
                    placeholder="e.g. bybit.eu"
                />
            </n-form-item>
        </n-form>
    </n-card>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import type { FormInst, FormRules } from 'naive-ui/es/form'

interface ExchangeAdvancedModel {
    exchange_hostname: string | null
}

defineProps<{
    exchange: ExchangeAdvancedModel
    rules: FormRules
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
