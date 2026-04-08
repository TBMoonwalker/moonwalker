<template>
    <n-card title="Exchange settings">
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
            <n-form-item label="Exchange" path="name">
                <n-select
                    v-model:value="exchange.name"
                    placeholder="Select"
                    :options="exchanges"
                />
            </n-form-item>
            <n-form-item label="Timerange" path="timeframe">
                <n-select
                    v-model:value="exchange.timeframe"
                    placeholder="Select"
                    :options="timerange"
                />
            </n-form-item>
            <n-form-item label="Key" path="key">
                <n-input
                    v-model:value="exchange.key"
                    type="password"
                    show-password-on="click"
                    placeholder="Exchange Key"
                />
            </n-form-item>
            <n-form-item label="Secret" path="secret">
                <n-input
                    v-model:value="exchange.secret"
                    type="password"
                    show-password-on="click"
                    placeholder="Exchange Secret"
                />
            </n-form-item>
            <n-form-item
                v-if="showAdvancedGeneral"
                label="Exchange Hostname"
                path="exchange_hostname"
            >
                <n-input
                    v-model:value="exchange.exchange_hostname"
                    placeholder="e.g. bybit.eu"
                />
            </n-form-item>
            <n-form-item label="Dry Run (Demo Trading)" path="dryrun" label-placement="left">
                <n-checkbox v-model:checked="exchange.dry_run" />
            </n-form-item>
            <n-form-item label="Currency" path="currency">
                <n-select
                    v-model:value="exchange.currency"
                    placeholder="Select"
                    :options="currency"
                />
            </n-form-item>
            <n-form-item label="Market" path="market">
                <n-select
                    v-model:value="exchange.market"
                    placeholder="Select"
                    :options="market"
                />
            </n-form-item>
            <n-form-item label="Use OHCLV" path="watcher" label-placement="left">
                <n-checkbox v-model:checked="exchange.watcher_ohlcv" />
            </n-form-item>
        </n-form>
    </n-card>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import type { FormInst, FormRules } from 'naive-ui/es/form'
import type { ExchangeModel, StringSelectOption } from '../../config-editor/types'

defineProps<{
    currency: StringSelectOption[]
    exchange: ExchangeModel
    exchanges: StringSelectOption[]
    market: StringSelectOption[]
    rules: FormRules
    showAdvancedGeneral: boolean
    timerange: StringSelectOption[]
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
