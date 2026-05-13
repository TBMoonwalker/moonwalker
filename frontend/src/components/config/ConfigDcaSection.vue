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
                <n-checkbox v-model:checked="dca.enabled" />
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
            <n-form-item label="Stop loss percentage" path="sl">
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
            <template v-if="dca.enabled">
                <n-alert
                    v-if="showSidestepSpotOnlyNotice"
                    class="sidestep-campaign-note"
                    type="info"
                    :bordered="false"
                >
                    Spot sidestep campaigns only run when the exchange market is set
                    to spot. You can keep these settings configured here, but the
                    service stays inactive on non-spot markets.
                </n-alert>
                <n-alert
                    v-if="isSidestepMode"
                    class="sidestep-campaign-note"
                    type="info"
                    :bordered="false"
                >
                    Sidestep mode keeps the trade active after selling. It waits
                    flat, tracks a virtual short-style PNL while price falls, and
                    re-enters from the watcher using its own re-entry strategy.
                </n-alert>
                <template v-if="isSidestepMode">
                    <n-form-item
                        label="Bearish sidestep strategy"
                        path="sidestep_bearish_strategy"
                    >
                        <n-select
                            v-model:value="dca.sidestep_bearish_strategy"
                            placeholder="Select"
                            :options="strategyOptions"
                        />
                    </n-form-item>
                    <n-form-item
                        label="Sidestep re-entry strategy"
                        path="sidestep_reentry_strategy"
                    >
                        <n-select
                            v-model:value="dca.sidestep_reentry_strategy"
                            placeholder="Select"
                            :options="strategyOptions"
                        />
                    </n-form-item>
                    <n-form-item
                        label="Re-entry cooldown (candles)"
                        path="sidestep_reentry_cooldown_candles"
                    >
                        <n-input-number
                            v-model:value="dca.sidestep_reentry_cooldown_candles"
                            :min="0"
                            placeholder="0"
                        />
                    </n-form-item>
                </template>
            </template>
        </n-form>
    </n-card>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { FormInst, FormRules } from 'naive-ui/es/form'
import type { DcaModel, StringSelectOption } from '../../config-editor/types'
import type { TradeModeSwitchGuardState } from '../../helpers/configLoad'
import {
    TRADE_MODE_DYNAMIC_DCA,
    TRADE_MODE_SIDESTEP,
    isDynamicTradeMode,
    isSidestepTradeMode,
} from '../../helpers/tradeLifecycle'

const props = defineProps<{
    dca: DcaModel
    market: string | null
    rules: FormRules
    sellOrderTypeOptions: StringSelectOption[]
    showAdvancedGeneral: boolean
    strategyOptions: StringSelectOption[]
    tradeModeSwitchGuard: TradeModeSwitchGuardState
}>()

const formRef = ref<FormInst | null>(null)
const tradeModeOptions: StringSelectOption[] = [
    { label: 'Dynamic DCA', value: TRADE_MODE_DYNAMIC_DCA },
    { label: 'Sidestep', value: TRADE_MODE_SIDESTEP },
]
const isDynamicDcaMode = computed(
    () => isDynamicTradeMode(props.dca.trade_mode),
)
const isSidestepMode = computed(
    () => isSidestepTradeMode(props.dca.trade_mode),
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
    if (props.tradeModeSwitchGuard.waiting_campaign_count > 0) {
        details.push(
            `${props.tradeModeSwitchGuard.waiting_campaign_count} waiting sidestep campaign(s)`,
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
const normalizedMarket = computed(() =>
    String(props.market || 'spot').trim().toLowerCase(),
)
const showSidestepSpotOnlyNotice = computed(
    () =>
        props.dca.enabled &&
        isSidestepMode.value &&
        normalizedMarket.value !== 'spot',
)

function isTradeModeOptionDisabled(value: string): boolean {
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

.sidestep-campaign-note {
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
</style>
