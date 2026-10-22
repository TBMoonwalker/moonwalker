<template>
    <n-card title="Trade modes">
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
                <n-checkbox v-model:checked="dca.enabled" :disabled="isAccumulationMode && dca.enabled" />
            </n-form-item>

            <template v-if="dca.enabled">
                <n-form-item label="Trade mode" path="trade_mode">
                    <n-radio-group
                        v-model:value="dca.trade_mode"
                        class="trade-mode-group"
                    >
                        <n-radio-button
                            v-for="option in tradeModeOptions"
                            :key="option.value"
                            :value="option.value"
                            :disabled="isTradeModeOptionDisabled(option.value)"
                        >
                            {{ option.label }}
                        </n-radio-button>
                    </n-radio-group>
                </n-form-item>
                <n-alert v-if="isAccumulationMode" type="info" :bordered="false" class="trade-mode-guard-note">
                    Accumulation uses available budget to build holdings. Sales are manual only; take profit, stop loss and base-order sizing do not apply. Newly available funds may be spent while enabled. Pause a holding or Moonwalker to stop new buys. Dry run trades against the exchange demo account when supported. It requires demo credentials and available demo funds; it never falls back to live trading.
                </n-alert>
                <n-form-item v-if="isAccumulationMode" label="Initial accumulation strategy version" path="accumulation_strategy_version_id" :label-props="{ for: 'config-accumulation-strategy' }">
                    <n-select filterable v-model:value="dca.accumulation_strategy_version_id" :options="accumulationStrategies" :fallback-option="(value: string | number) => ({ value, label: 'Saved version — load the catalog to inspect' })" :loading="accumulationLoading" :disabled="!dca.accumulation_available" :input-props="{ id: 'config-accumulation-strategy' }" placeholder="Select an exact compatible saved version" />
                </n-form-item>
                <template v-if="isAccumulationMode">
                    <p v-if="accumulationError" role="alert">{{ accumulationError }}</p>
                    <n-space>
                        <n-button :disabled="!dca.accumulation_available || accumulationLoading" @click="loadAccumulationStrategies()">Refresh strategies</n-button>
                        <n-button v-if="accumulationCursor !== null" :disabled="accumulationLoading" @click="loadAccumulationStrategies(true)">Load more strategies</n-button>
                        <RouterLink class="accumulation-builder-link" :to="{ name: 'controlCenter', query: { mode: 'strategy-builder', target: 'strategy-builder' } }">Create in Strategy Builder</RouterLink>
                    </n-space>
                    <p>The initial version applies to new registrations. Existing holdings keep their pin; switch them from Trading Overview. You can save an incomplete dry-run draft before creating a strategy.</p>
                </template>
                <n-alert
                    v-if="tradeModeSwitchNotice"
                    class="trade-mode-guard-note"
                    type="warning"
                    :bordered="false"
                >
                    {{ tradeModeSwitchNotice }}
                </n-alert>
                <n-form-item
                    v-if="isDynamicDcaMode"
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

            <n-form-item v-if="!isAccumulationMode" label="Take profit percentage" path="tp">
                <n-input-number v-model:value="dca.tp" placeholder="TP" />
            </n-form-item>
            <n-form-item v-if="!isAccumulationMode" label="Trailing Take profit percentage" path="ttp">
                <n-input-number v-model:value="dca.trailing_tp" placeholder="TTP" />
            </n-form-item>
            <n-form-item :label="isAccumulationMode ? 'Max managed symbols' : 'Max bots running'" path="max_bots">
                <n-input-number v-model:value="dca.max_bots" placeholder="Bot count" />
            </n-form-item>
            <n-form-item v-if="!isAccumulationMode || signalName === 'asap'" :label="isAccumulationMode ? 'Initial buy amount' : 'Base order amount'" path="bo">
                <n-input-number v-model:value="dca.bo" placeholder="BO" />
            </n-form-item>
            <n-form-item v-if="!isAccumulationMode" label="Sell order type" path="sell_order_type">
                <n-select
                    v-model:value="dca.sell_order_type"
                    placeholder="Select"
                    :options="sellOrderTypeOptions"
                />
            </n-form-item>
            <template v-if="!isAccumulationMode && dca.sell_order_type === 'limit'">
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
            <template v-if="!isAccumulationMode && showAdvancedGeneral">
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
                v-if="dca.enabled && isDynamicDcaMode"
                label="Max safety order count"
                path="mstc"
            >
                <n-input-number v-model:value="dca.mstc" placeholder="MSTC" />
            </n-form-item>
            <n-form-item
                v-if="dca.enabled && isDynamicDcaMode"
                label="Price deviation for first safety order"
                path="sos"
            >
                <n-input-number v-model:value="dca.sos" placeholder="SOS" />
            </n-form-item>
            <n-form-item v-if="!isAccumulationMode" label="Stop loss percentage" path="sl">
                <n-input-number v-model:value="dca.sl" placeholder="SL" />
            </n-form-item>
            <n-form-item
                v-if="dca.enabled && isDynamicDcaMode"
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
import { computed, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { fetchAccumulationStrategies } from '../../api/accumulation'
import type { FormInst, FormRules } from 'naive-ui/es/form'
import type { DcaModel, StringSelectOption } from '../../config-editor/types'
import type { TradeModeSwitchGuardState } from '../../helpers/configLoad'
import {
    TRADE_MODE_DYNAMIC_DCA,
    TRADE_MODE_ACCUMULATION,
    isDynamicTradeMode,
} from '../../helpers/tradeLifecycle'

const props = defineProps<{
     dca: DcaModel
     signalName?: string | null
     rules: FormRules
    sellOrderTypeOptions: StringSelectOption[]
    showAdvancedGeneral: boolean
    strategyOptions: StringSelectOption[]
    tradeModeSwitchGuard: TradeModeSwitchGuardState
}>()

const formRef = ref<FormInst | null>(null)
const tradeModeOptions: StringSelectOption[] = [
    { label: 'Dynamic DCA', value: TRADE_MODE_DYNAMIC_DCA },
    { label: 'Accumulation', value: TRADE_MODE_ACCUMULATION },
]
const isAccumulationMode = computed(() => props.dca.trade_mode === TRADE_MODE_ACCUMULATION)
const accumulationStrategies = ref<{ label: string; value: number }[]>([])
const accumulationCursor = ref<number | null>(null)
const accumulationLoading = ref(false)
const accumulationError = ref('')
async function loadAccumulationStrategies(more = false) {
    if (!props.dca.accumulation_available || accumulationLoading.value) return
    accumulationLoading.value = true
    try {
        const page = await fetchAccumulationStrategies(more ? accumulationCursor.value ?? 0 : 0)
        const options = page.versions.map(version => ({ label: `${version.name} · v${version.version} · ${version.parameters.timeframe}`, value: version.id }))
        accumulationStrategies.value = more ? [...accumulationStrategies.value, ...options.filter(option => !accumulationStrategies.value.some(old => old.value === option.value))] : options
        accumulationCursor.value = page.next_after_id
        accumulationError.value = ''
    } catch { accumulationError.value = 'Could not load compatible accumulation strategies.' }
    finally { accumulationLoading.value = false }
}
watch(() => props.dca.accumulation_available, available => { if (available) void loadAccumulationStrategies() }, { immediate: true })
const isDynamicDcaMode = computed(
    () => isDynamicTradeMode(props.dca.trade_mode),
)
const tradeModeSwitchNotice = computed(() => {
    if (!props.tradeModeSwitchGuard?.blocked) {
        return null
      }
    const details: string[] = []
    if (props.tradeModeSwitchGuard.open_trade_count > 0) {
        details.push(
             `${props.tradeModeSwitchGuard.open_trade_count} open trade(s)`,
        )
     }
    const detailText =
        details.length > 0 ? ` Current blockers: ${details.join(', ')}.` : ''
    return `${props.tradeModeSwitchGuard.message || 'Trade mode switching is temporarily locked.'}${detailText}`
})
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

function isTradeModeOptionDisabled(value: string): boolean {
    if (value === TRADE_MODE_ACCUMULATION && !props.dca.accumulation_available) return true
    return Boolean(
        props.tradeModeSwitchGuard?.blocked &&
            props.tradeModeSwitchGuard.current_trade_mode &&
            props.tradeModeSwitchGuard.current_trade_mode !== value,
    )
}

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

.trade-mode-group {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
}

.trade-mode-guard-note {
    margin-bottom: 18px;
}
.accumulation-builder-link { display: inline-flex; align-items: center; min-height: 44px; }
</style>
