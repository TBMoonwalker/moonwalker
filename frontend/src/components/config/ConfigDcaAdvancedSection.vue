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

            <template
                v-if="dca.enabled && dca.trade_mode === 'dynamic_dca'"
            >
                <n-divider title-placement="left">
                    Recovery safety orders
                </n-divider>
                <n-form-item label="Sizing mode" path="dynamic_so_sizing_mode">
                    <n-select
                        v-model:value="dca.dynamic_so_sizing_mode"
                        :options="recoverySizingModeOptions"
                    />
                </n-form-item>
                <n-alert
                    class="recovery-mode-note"
                    :type="isRecoveryTargetMode ? 'warning' : 'info'"
                    :bordered="false"
                >
                    {{ recoveryModeExplanation }} Policy changes are snapshotted
                    only when a new deal opens; existing deals keep their current
                    sizing mode.
                </n-alert>
                <template v-if="isRecoveryMode">
                    <n-form-item
                        label="ATR timeframe source"
                        path="dynamic_so_atr_timeframe"
                    >
                        <n-select
                            v-model:value="dca.dynamic_so_atr_timeframe"
                            :options="atrTimeframeOptions"
                        />
                    </n-form-item>
                    <n-form-item
                        label="ATR length"
                        path="dynamic_so_atr_length"
                    >
                        <n-input-number
                            v-model:value="dca.dynamic_so_atr_length"
                            :min="2"
                            :step="1"
                        />
                    </n-form-item>
                    <n-form-item
                        label="Spacing ATR multiplier"
                        path="dynamic_so_spacing_atr_multiplier"
                    >
                        <n-input-number
                            v-model:value="dca.dynamic_so_spacing_atr_multiplier"
                            :min="0"
                            :step="0.1"
                        />
                    </n-form-item>
                    <n-form-item label="Spacing step scale" path="ss">
                        <n-input-number
                            v-model:value="dca.ss"
                            :min="1"
                            :step="0.1"
                        />
                    </n-form-item>
                    <n-form-item
                        label="Recovery ATR multiplier"
                        path="dynamic_so_recovery_atr_multiplier"
                    >
                        <n-input-number
                            v-model:value="dca.dynamic_so_recovery_atr_multiplier"
                            :min="0"
                            :step="0.1"
                        />
                    </n-form-item>
                    <n-form-item
                        label="Minimum recovery move (%)"
                        path="dynamic_so_recovery_min_pct"
                    >
                        <n-input-number
                            v-model:value="dca.dynamic_so_recovery_min_pct"
                            :min="0"
                            :step="0.5"
                        />
                    </n-form-item>
                    <n-form-item
                        label="Maximum recovery move (%)"
                        path="dynamic_so_recovery_max_pct"
                    >
                        <n-input-number
                            v-model:value="dca.dynamic_so_recovery_max_pct"
                            :min="0"
                            :step="0.5"
                        />
                    </n-form-item>
                    <n-form-item
                        label="Maximum quote per deal"
                        path="dynamic_so_max_deal_quote"
                    >
                        <n-input-number
                            v-model:value="dca.dynamic_so_max_deal_quote"
                            :min="0"
                            :step="10"
                        />
                    </n-form-item>
                    <n-form-item
                        label="Minimum TP improvement (%)"
                        path="dynamic_so_min_tp_improvement_pct"
                    >
                        <n-input-number
                            v-model:value="dca.dynamic_so_min_tp_improvement_pct"
                            :min="0"
                            :step="0.5"
                        />
                    </n-form-item>
                    <n-form-item
                        label="Wick execution guard"
                        path="dynamic_so_execution_guard_enabled"
                        label-placement="left"
                    >
                        <n-checkbox
                            v-model:checked="
                                dca.dynamic_so_execution_guard_enabled
                            "
                        />
                    </n-form-item>
                    <template v-if="dca.dynamic_so_execution_guard_enabled">
                        <n-alert
                            class="recovery-mode-note"
                            type="info"
                            :bordered="false"
                        >
                            Recovery SOs use an executable ask check and a capped
                            immediate-or-cancel buy. Orders above the dynamic
                            ceiling are skipped.
                        </n-alert>
                        <n-form-item
                            label="Execution drift ATR fraction"
                            path="dynamic_so_execution_drift_atr_fraction"
                        >
                            <n-input-number
                                v-model:value="
                                    dca.dynamic_so_execution_drift_atr_fraction
                                "
                                :min="0"
                                :step="0.05"
                            />
                        </n-form-item>
                        <n-form-item
                            label="Minimum execution drift (%)"
                            path="dynamic_so_execution_drift_min_pct"
                        >
                            <n-input-number
                                v-model:value="
                                    dca.dynamic_so_execution_drift_min_pct
                                "
                                :min="0"
                                :step="0.05"
                            />
                        </n-form-item>
                        <n-form-item
                            label="Maximum execution drift (%)"
                            path="dynamic_so_execution_drift_max_pct"
                        >
                            <n-input-number
                                v-model:value="
                                    dca.dynamic_so_execution_drift_max_pct
                                "
                                :min="0"
                                :step="0.05"
                            />
                        </n-form-item>
                    </template>
                </template>
            </template>
        </n-form>
    </n-card>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { FormInst, FormRules } from 'naive-ui/es/form'
import type { DcaAdvancedModel } from '../../config-editor/types'

const props = defineProps<{
    dca: DcaAdvancedModel
    rules: FormRules
}>()

const recoverySizingModeOptions = [
    { label: 'Legacy factors', value: 'legacy_factors' },
    { label: 'Recovery shadow', value: 'recovery_shadow' },
    { label: 'Recovery target', value: 'recovery_target' },
]
const timeframeMinutes: Record<string, number> = {
    '1m': 1,
    '15m': 15,
    '30m': 30,
    '1h': 60,
    '4h': 4 * 60,
    '1d': 24 * 60,
    '1w': 7 * 24 * 60,
}
const atrTimeframeOptions = computed(() => {
    const tradingTimeframe = String(props.dca.timeframe || '')
    const tradingMinutes = timeframeMinutes[tradingTimeframe] ?? 0
    const higherTimeframes = Object.entries(timeframeMinutes)
        .filter(([, minutes]) => minutes > tradingMinutes)
        .map(([value]) => ({ label: value, value }))
    return [
        {
            label: `Trading candles (${tradingTimeframe || 'configured timeframe'})`,
            value: 'trading',
        },
        ...higherTimeframes,
    ]
})
const isRecoveryMode = computed(() =>
    ['recovery_shadow', 'recovery_target'].includes(
        String(props.dca.dynamic_so_sizing_mode),
    ),
)
const isRecoveryTargetMode = computed(
    () => props.dca.dynamic_so_sizing_mode === 'recovery_target',
)
const recoveryModeExplanation = computed(() => {
    if (props.dca.dynamic_so_sizing_mode === 'recovery_target') {
        return 'Live SOs use ATR spacing and size toward a reachable projected TP, within the deal budget.'
    }
    if (props.dca.dynamic_so_sizing_mode === 'recovery_shadow') {
        return 'Legacy orders remain active while recovery sizing is calculated for diagnostics.'
    }
    return 'The current loss, ATH and volatility factor sizing remains active.'
})

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

<style scoped>
.recovery-mode-note {
    margin-bottom: 18px;
}
</style>
