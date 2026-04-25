<template>
    <n-card :title="cardTitle === null ? undefined : cardTitle ?? 'Capital budget'">
        <n-form
            ref="formRef"
            :model="capital"
            :rules="rules"
            label-width="auto"
            require-mark-placement="right-hanging"
            :style="{
                maxWidth: '640px',
            }"
        >
            <n-form-item label="Global max fund" path="max_fund">
                <n-input-number
                    v-model:value="capital.max_fund"
                    placeholder="Global max fund"
                    :min="0"
                />
            </n-form-item>
            <n-form-item
                label="Reserve safety-order budget"
                path="reserve_safety_orders"
                label-placement="left"
            >
                <n-checkbox v-model:checked="capital.reserve_safety_orders" />
            </n-form-item>
            <n-form-item label="Budget buffer (%)" path="budget_buffer_pct">
                <n-input-number
                    v-model:value="capital.budget_buffer_pct"
                    placeholder="0"
                    :min="0"
                    :step="0.01"
                />
            </n-form-item>
        </n-form>
    </n-card>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import type { FormInst, FormRules } from 'naive-ui/es/form'
import type { CapitalModel } from '../../config-editor/types'

withDefaults(
    defineProps<{
        capital: CapitalModel
        cardTitle?: string | null
        rules: FormRules
    }>(),
    {
        cardTitle: undefined,
    },
)

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
