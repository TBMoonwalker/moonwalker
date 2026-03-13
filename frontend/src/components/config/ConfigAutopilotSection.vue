<template>
    <n-card title="Autopilot settings">
        <n-form
            ref="formRef"
            :model="autopilot"
            :rules="rules"
            label-width="auto"
            require-mark-placement="right-hanging"
            :style="{
                maxWidth: '640px',
            }"
        >
            <n-form-item label="Enabled" path="enabled" label-placement="left">
                <n-checkbox v-model:checked="autopilot.enabled" />
            </n-form-item>

            <template v-if="showFields">
                <n-form-item label="Max fund" path="maxfund">
                    <n-input-number
                        v-model:value="autopilot.max_fund"
                        placeholder="Max fund"
                    />
                </n-form-item>
                <n-form-item label="Max bots for high setting" path="highmad">
                    <n-input-number
                        v-model:value="autopilot.high_mad"
                        placeholder="Max bots high"
                    />
                </n-form-item>
                <n-form-item label="Take profit for high setting" path="hightp">
                    <n-input-number
                        v-model:value="autopilot.high_tp"
                        placeholder="Take profit high"
                    />
                </n-form-item>
                <n-form-item label="Stop loss for high setting" path="highsl">
                    <n-input-number
                        v-model:value="autopilot.high_sl"
                        placeholder="Stop loss high"
                    />
                </n-form-item>
                <n-form-item
                    label="Time threshold (in days) for stop loss"
                    path="highsl_timeout"
                >
                    <n-input-number
                        v-model:value="autopilot.high_sl_timeout"
                        placeholder="Stop loss timeout"
                    />
                </n-form-item>
                <n-form-item
                    label="Max threshold (in percent of max fund) for high setting"
                    path="high_threshold"
                >
                    <n-input-number
                        v-model:value="autopilot.high_threshold"
                        placeholder="Fund threshold"
                    />
                </n-form-item>
                <n-form-item label="Max bots for medium setting" path="mediummad">
                    <n-input-number
                        v-model:value="autopilot.medium_mad"
                        placeholder="Max bots medium"
                    />
                </n-form-item>
                <n-form-item label="Take profit for medium setting" path="mediumtp">
                    <n-input-number
                        v-model:value="autopilot.medium_tp"
                        placeholder="Take profit medium"
                    />
                </n-form-item>
                <n-form-item label="Stop loss for medium setting" path="highsl">
                    <n-input-number
                        v-model:value="autopilot.medium_sl"
                        placeholder="Stop loss medium"
                    />
                </n-form-item>
                <n-form-item
                    label="Time threshold (in days) for stop loss"
                    path="mediumsl_timeout"
                >
                    <n-input-number
                        v-model:value="autopilot.medium_sl_timeout"
                        placeholder="Stop loss timeout"
                    />
                </n-form-item>
                <n-form-item
                    label="Max threshold (in percent of max fund) for medium setting"
                    path="medium_threshold"
                >
                    <n-input-number
                        v-model:value="autopilot.medium_threshold"
                        placeholder="Fund threshold"
                    />
                </n-form-item>
            </template>
        </n-form>
    </n-card>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import type { FormInst, FormRules } from 'naive-ui/es/form'

interface AutopilotModel {
    enabled: boolean
    max_fund: number | null
    high_mad: number | null
    high_tp: number | null
    high_sl: number | null
    high_sl_timeout: number | null
    high_threshold: number | null
    medium_mad: number | null
    medium_tp: number | null
    medium_sl: number | null
    medium_sl_timeout: number | null
    medium_threshold: number | null
}

defineProps<{
    autopilot: AutopilotModel
    rules: FormRules
    showFields: boolean
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
