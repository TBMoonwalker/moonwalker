<template>
    <n-card>
        <n-form
            ref="formRef"
            :model="dca"
            :rules="rules"
            label-width="auto"
            require-mark-placement="right-hanging"
            :style="{
                maxWidth: '640px',
            }"
        >
            <n-form-item
                label="TP spike confirmation"
                path="tp_spike_confirm_enabled"
                label-placement="left"
            >
                <n-checkbox v-model:checked="dca.tp_spike_confirm_enabled" />
            </n-form-item>
            <template v-if="dca.tp_spike_confirm_enabled">
                <n-form-item
                    label="TP confirmation window (seconds)"
                    path="tp_spike_confirm_seconds"
                >
                    <n-input-number
                        v-model:value="dca.tp_spike_confirm_seconds"
                        :min="0"
                        placeholder="3"
                    />
                </n-form-item>
                <n-form-item
                    label="Minimum qualifying TP ticks"
                    path="tp_spike_confirm_ticks"
                >
                    <n-input-number
                        v-model:value="dca.tp_spike_confirm_ticks"
                        :min="0"
                        placeholder="0"
                    />
                </n-form-item>
            </template>
        </n-form>
    </n-card>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import type { FormInst, FormRules } from 'naive-ui/es/form'

interface DcaAdvancedModel {
    tp_spike_confirm_enabled: boolean
    tp_spike_confirm_seconds: number
    tp_spike_confirm_ticks: number
}

defineProps<{
    dca: DcaAdvancedModel
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
