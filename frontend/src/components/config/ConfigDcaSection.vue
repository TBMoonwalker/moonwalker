<template>
    <n-card title="DCA settings">
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
            <n-form-item label="Enabled" path="enabled" label-placement="left">
                <n-checkbox v-model:checked="dca.enabled" />
            </n-form-item>

            <template v-if="dca.enabled">
                <n-form-item
                    label="Dynamic DCA"
                    path="dynamic_dca"
                    label-placement="left"
                >
                    <n-checkbox v-model:checked="dca.dynamic" />
                </n-form-item>
                <n-form-item
                    v-if="dca.dynamic"
                    label="Dynamic DCA strategy"
                    path="strategy.0"
                >
                    <n-select
                        v-model:value="dca.strategy"
                        placeholder="Select"
                        :options="strategyOptions"
                    />
                </n-form-item>
            </template>

            <n-form-item label="Take profit percentage" path="tp">
                <n-input-number v-model:value="dca.tp" placeholder="TP" />
            </n-form-item>
            <n-form-item label="Trailing Take profit percentage" path="ttp">
                <n-input-number v-model:value="dca.trailing_tp" placeholder="TTP" />
            </n-form-item>
            <n-form-item label="Max bots running" path="max_bots">
                <n-input-number v-model:value="dca.max_bots" placeholder="Bot count" />
            </n-form-item>
            <n-form-item label="Base order amount" path="bo">
                <n-input-number v-model:value="dca.bo" placeholder="BO" />
            </n-form-item>
            <n-form-item label="Sell order type" path="sell_order_type">
                <n-select
                    v-model:value="dca.sell_order_type"
                    placeholder="Select"
                    :options="sellOrderTypeOptions"
                />
            </n-form-item>
            <template v-if="dca.sell_order_type === 'limit'">
                <n-form-item
                    label="Limit sell timeout (seconds)"
                    path="limit_sell_timeout_sec"
                >
                    <n-input-number
                        v-model:value="dca.limit_sell_timeout_sec"
                        placeholder="60"
                    />
                </n-form-item>
                <n-form-item
                    label="Fallback to market sell on timeout"
                    path="limit_sell_fallback_to_market"
                    label-placement="left"
                >
                    <n-checkbox
                        v-model:checked="dca.limit_sell_fallback_to_market"
                    />
                </n-form-item>
                <n-form-item
                    label="Pre-arm TP limit order"
                    path="tp_limit_prearm_enabled"
                    label-placement="left"
                >
                    <n-checkbox v-model:checked="dca.tp_limit_prearm_enabled" />
                </n-form-item>
                <n-alert
                    v-if="showTpLimitPrearmConflictWarning"
                    class="tp-limit-prearm-warning"
                    type="warning"
                    :bordered="false"
                >
                    {{ tpLimitPrearmConflictWarningText }}
                </n-alert>
                <n-form-item
                    v-if="dca.tp_limit_prearm_enabled"
                    label="TP pre-arm margin (%)"
                    path="tp_limit_prearm_margin_percent"
                >
                    <n-input-number
                        v-model:value="dca.tp_limit_prearm_margin_percent"
                        :min="0"
                        placeholder="0.25"
                    />
                </n-form-item>
            </template>
            <template v-if="showAdvancedGeneral">
                <n-form-item
                    label="TP spike confirmation"
                    path="tp_spike_confirm_enabled"
                    label-placement="left"
                >
                    <n-checkbox
                        v-model:checked="dca.tp_spike_confirm_enabled"
                    />
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
            </template>
            <n-form-item
                v-if="dca.enabled && !dca.dynamic"
                label="Safety order amount"
                path="so"
            >
                <n-input-number v-model:value="dca.so" placeholder="SO" />
            </n-form-item>
            <n-form-item v-if="dca.enabled" label="Max safety order count" path="mstc">
                <n-input-number v-model:value="dca.mstc" placeholder="MSTC" />
            </n-form-item>
            <n-form-item
                v-if="dca.enabled"
                label="Price deviation for first safety order"
                path="sos"
            >
                <n-input-number v-model:value="dca.sos" placeholder="SOS" />
            </n-form-item>
            <n-form-item
                v-if="dca.enabled && !dca.dynamic"
                label="Safety order step scale"
                path="ss"
            >
                <n-input-number v-model:value="dca.ss" placeholder="SS" />
            </n-form-item>
            <n-form-item
                v-if="dca.enabled && !dca.dynamic"
                label="Safety order volume scale"
                path="os"
            >
                <n-input-number v-model:value="dca.os" placeholder="OS" />
            </n-form-item>
            <n-form-item label="Stop loss percentage" path="sl">
                <n-input-number v-model:value="dca.sl" placeholder="SL" />
            </n-form-item>
            <n-form-item
                v-if="dca.enabled && dca.dynamic"
                label="Safety order budget ratio"
                path="trade_safety_order_budget_ratio"
            >
                <n-input-number
                    v-model:value="dca.trade_safety_order_budget_ratio"
                    :min="0.01"
                    :max="1"
                    :step="0.01"
                    placeholder="0.95"
                />
            </n-form-item>
        </n-form>
    </n-card>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { FormInst, FormRules } from 'naive-ui/es/form'
import type { DcaModel, StringSelectOption } from '../../config-editor/types'

const props = defineProps<{
    dca: DcaModel
    rules: FormRules
    sellOrderTypeOptions: StringSelectOption[]
    showAdvancedGeneral: boolean
    strategyOptions: StringSelectOption[]
}>()

const formRef = ref<FormInst | null>(null)
const tpLimitPrearmConflictNames = computed(() => {
    if (!props.dca.tp_limit_prearm_enabled) {
        return []
    }

    const conflicts: string[] = []
    const trailingTp = Number(props.dca.trailing_tp ?? 0)
    if (Number.isFinite(trailingTp) && trailingTp > 0) {
        conflicts.push('trailing TP')
    }
    if (props.dca.tp_spike_confirm_enabled) {
        conflicts.push('TP spike confirmation')
    }
    return conflicts
})
const showTpLimitPrearmConflictWarning = computed(
    () => tpLimitPrearmConflictNames.value.length > 0,
)
const tpLimitPrearmConflictWarningText = computed(() => {
    const conflicts = tpLimitPrearmConflictNames.value
    if (conflicts.length === 0) {
        return ''
    }
    const conflictList =
        conflicts.length === 1
            ? conflicts[0]
            : `${conflicts.slice(0, -1).join(', ')} and ${
                  conflicts[conflicts.length - 1]
              }`
    return `TP limit pre-arm does not support ${conflictList}. Disable ${conflictList} before using pre-armed limit exits.`
})

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

<style scoped>
.tp-limit-prearm-warning {
    margin-bottom: 18px;
}
</style>
