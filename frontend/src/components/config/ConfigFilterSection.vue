<template>
    <n-card :title="cardTitle === null ? undefined : cardTitle ?? 'Filter settings'">
        <n-form
            ref="formRef"
            :model="filter"
            :rules="rules"
            label-width="auto"
            require-mark-placement="right-hanging"
            :style="{
                maxWidth: '640px',
            }"
        >
            <n-form-item label="Denylist" path="denylist">
                <n-input
                    v-model:value="filter.denylist"
                    placeholder="Textarea"
                    type="textarea"
                    :autosize="{
                        minRows: 3,
                        maxRows: 5,
                    }"
                />
            </n-form-item>
            <template v-if="showAsapFields">
                <n-form-item label="RSI Maximum" path="rsi.0">
                    <n-input-number
                        v-model:value="filter.rsi"
                        placeholder="RSI Maximum"
                    />
                </n-form-item>
                <n-form-item label="CMC API Key" path="cmc_api_key.0">
                    <n-input
                        v-model:value="filter.cmc_api_key"
                        type="password"
                        show-password-on="click"
                        placeholder="CMC API Key"
                    />
                </n-form-item>
            </template>

            <n-form-item label="Topcoin Limit" path="topcoin_limit">
                <n-input-number
                    v-model:value="filter.topcoin_limit"
                    placeholder="Topcoin Limit"
                />
            </n-form-item>

            <n-form-item label="Volume Limit" path="volume_limit">
                <n-input-number
                    v-model:value="filter.volume"
                    placeholder="Volume Limit"
                />
            </n-form-item>

            <n-form-item label="BTC Pulse" path="btc_pulse" label-placement="left">
                <n-checkbox v-model:checked="filter.btc_pulse" />
            </n-form-item>
        </n-form>
    </n-card>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import type { FormInst, FormRules } from 'naive-ui/es/form'
import type { FilterModel } from '../../config-editor/types'

defineProps<{
    filter: FilterModel
    rules: FormRules
    showAsapFields: boolean
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
