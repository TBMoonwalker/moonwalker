<template>
    <n-card :title="cardTitle === null ? undefined : cardTitle ?? 'Autopilot settings'">
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
                <n-form-item
                    label="Per-symbol entry sizing"
                    path="symbol_entry_sizing_enabled"
                    label-placement="left"
                >
                    <n-checkbox v-model:checked="autopilot.symbol_entry_sizing_enabled" />
                </n-form-item>
                <n-form-item
                    label="Profit stretch"
                    path="profit_stretch_enabled"
                    label-placement="left"
                >
                    <n-checkbox v-model:checked="autopilot.profit_stretch_enabled" />
                </n-form-item>
                <template v-if="autopilot.profit_stretch_enabled">
                    <n-form-item label="Stretch ratio" path="profit_stretch_ratio">
                        <n-input-number
                            v-model:value="autopilot.profit_stretch_ratio"
                            placeholder="0"
                            :min="0"
                            :step="0.05"
                        />
                    </n-form-item>
                    <n-form-item label="Stretch cap" path="profit_stretch_max">
                        <n-input-number
                            v-model:value="autopilot.profit_stretch_max"
                            placeholder="0"
                            :min="0"
                        />
                    </n-form-item>
                    <n-form-item
                        label="Base order stretch multiplier"
                        path="base_order_stretch_max_multiplier"
                    >
                        <n-input-number
                            v-model:value="autopilot.base_order_stretch_max_multiplier"
                            placeholder="1"
                            :min="1"
                            :step="0.05"
                        />
                    </n-form-item>
                </template>
                <n-divider />
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
                <n-divider />
                <n-form-item
                    label="Green phase boost"
                    path="green_phase_enabled"
                    label-placement="left"
                >
                    <n-checkbox v-model:checked="autopilot.green_phase_enabled" />
                </n-form-item>
                <template v-if="autopilot.green_phase_enabled">
                    <n-form-item label="Ramp-up history (days)" path="green_phase_ramp_days">
                        <n-input-number
                            v-model:value="autopilot.green_phase_ramp_days"
                            placeholder="30"
                            :min="1"
                        />
                    </n-form-item>
                    <n-form-item label="Evaluation interval (seconds)" path="green_phase_eval_interval_sec">
                        <n-input-number
                            v-model:value="autopilot.green_phase_eval_interval_sec"
                            placeholder="60"
                            :min="5"
                        />
                    </n-form-item>
                    <n-form-item label="Recent speed window (minutes)" path="green_phase_window_minutes">
                        <n-input-number
                            v-model:value="autopilot.green_phase_window_minutes"
                            placeholder="60"
                            :min="5"
                        />
                    </n-form-item>
                    <n-form-item label="Minimum profitable close ratio" path="green_phase_min_profitable_close_ratio">
                        <n-input-number
                            v-model:value="autopilot.green_phase_min_profitable_close_ratio"
                            placeholder="0.8"
                            :min="0"
                            :max="1"
                            :step="0.05"
                        />
                    </n-form-item>
                    <n-form-item label="Speed multiplier to enter green phase" path="green_phase_speed_multiplier">
                        <n-input-number
                            v-model:value="autopilot.green_phase_speed_multiplier"
                            placeholder="1.5"
                            :min="1"
                            :step="0.05"
                        />
                    </n-form-item>
                    <n-form-item label="Speed multiplier to exit green phase" path="green_phase_exit_multiplier">
                        <n-input-number
                            v-model:value="autopilot.green_phase_exit_multiplier"
                            placeholder="1.15"
                            :min="0.5"
                            :step="0.05"
                        />
                    </n-form-item>
                    <n-form-item label="Maximum extra deals" path="green_phase_max_extra_deals">
                        <n-input-number
                            v-model:value="autopilot.green_phase_max_extra_deals"
                            placeholder="2"
                            :min="0"
                        />
                    </n-form-item>
                    <n-form-item label="Confirm cycles to activate" path="green_phase_confirm_cycles">
                        <n-input-number
                            v-model:value="autopilot.green_phase_confirm_cycles"
                            placeholder="2"
                            :min="1"
                        />
                    </n-form-item>
                    <n-form-item label="Release cycles to exit" path="green_phase_release_cycles">
                        <n-input-number
                            v-model:value="autopilot.green_phase_release_cycles"
                            placeholder="4"
                            :min="1"
                        />
                    </n-form-item>
                    <n-form-item label="Hard locked-fund ceiling (%)" path="green_phase_max_locked_fund_percent">
                        <n-input-number
                            v-model:value="autopilot.green_phase_max_locked_fund_percent"
                            placeholder="85"
                            :min="0"
                            :max="100"
                            :step="1"
                        />
                    </n-form-item>
                </template>
            </template>
        </n-form>
    </n-card>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import type { FormInst, FormRules } from 'naive-ui/es/form'
import type { AutopilotModel } from '../../config-editor/types'

defineProps<{
    autopilot: AutopilotModel
    rules: FormRules
    showFields: boolean
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
