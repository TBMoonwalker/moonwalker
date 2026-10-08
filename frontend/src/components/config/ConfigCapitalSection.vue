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
            <n-form-item v-if="showBaseFields" label="Global max fund" path="max_fund">
                <n-input-number
                    v-model:value="capital.max_fund"
                    placeholder="Global max fund"
                    :min="0"
                />
            </n-form-item>
            <n-form-item
                v-if="showExpertFields"
                path="reserve_safety_orders"
                :show-label="false"
            >
                <div class="capital-field">
                    <n-checkbox
                        v-model:checked="capital.reserve_safety_orders"
                        aria-label="Reserve safety-order budget"
                        aria-describedby="capital-reserve-help"
                    >
                        Reserve safety-order budget
                    </n-checkbox>
                    <p id="capital-reserve-help" class="capital-help">
                        Sets aside the base order amount for each remaining safety order in open deals.
                        This is not a percentage of your capital limit.
                    </p>
                    <div class="capital-estimate" aria-live="polite" aria-atomic="true">
                        <template v-if="preview && !capital.reserve_safety_orders">
                            Safety-order reserve: <strong>{{ quote(0) }}</strong> (disabled).
                        </template>
                        <template v-else-if="preview && preview.openDealReserve !== null">
                            Estimated reserve for {{ preview.openDealCount }} open {{ preview.openDealCount === 1 ? 'deal' : 'deals' }}:
                            <strong>{{ quote(preview.openDealReserve) }}</strong>
                            <p class="capital-help">
                                {{ preview.remainingSafetyOrders }} remaining safety {{ preview.remainingSafetyOrders === 1 ? 'order' : 'orders' }}
                                × {{ quote(preview.baseOrderSize) }}. Uses your draft settings; pending orders are separate.
                            </p>
                        </template>
                        <template v-else>
                            {{ preview ? 'Connect to the live trade feed to estimate the reserve for open deals.' : 'Enter a base order amount and a whole safety-order count in Setup to see an estimate.' }}
                        </template>
                    </div>
                </div>
            </n-form-item>
            <n-form-item
                v-if="showExpertFields && dynamicDcaEnabled"
                label="Budget buffer for dynamic safety orders (%)"
                path="budget_buffer_pct"
            >
                <div class="capital-field">
                    <n-input-number
                        v-model:value="capital.budget_buffer_pct"
                        placeholder="0"
                        :min="0"
                        :step="0.01"
                        aria-describedby="capital-buffer-help"
                    />
                    <p id="capital-buffer-help" class="capital-help">
                        Adds a buffer to the budget checked for a new buy, not to the capital limit
                        or the displayed reserve for open deals.
                    </p>
                    <div v-if="preview" class="capital-estimate" aria-live="polite" aria-atomic="true">
                        Budget checked for one new deal: <strong>{{ quote(preview.newDealRequirement) }}</strong>
                        <p class="capital-help">
                            {{ quote(preview.baseOrderSize) }} base order + {{ quote(preview.newDealReserve) }} safety-order reserve
                            + {{ quote(preview.newDealBuffer) }} buffer ({{ preview.bufferPercent }}%).
                            Actual order sizes may vary.
                        </p>
                    </div>
                </div>
            </n-form-item>
        </n-form>
    </n-card>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { FormInst, FormRules } from 'naive-ui/es/form'
import type { CapitalModel } from '../../config-editor/types'
import { calculateCapitalBudgetPreview } from '../../helpers/capitalBudgetPreview'
import { useWebSocketDataStore } from '../../stores/websocket'

const props = withDefaults(
    defineProps<{
        capital: CapitalModel
        baseOrderSize: number | null
        maxSafetyOrders: number | null
        quoteCurrency: string | null
        cardTitle?: string | null
        dynamicDcaEnabled: boolean
        rules: FormRules
        showBaseFields?: boolean
        showExpertFields?: boolean
    }>(),
    {
        cardTitle: undefined,
        showBaseFields: true,
        showExpertFields: true,
    },
)

const formRef = ref<FormInst | null>(null)
const openTrades = useWebSocketDataStore('openTrades')
const preview = computed(() => calculateCapitalBudgetPreview({
    baseOrderSize: props.baseOrderSize,
    maxSafetyOrders: props.maxSafetyOrders,
    reserveSafetyOrders: props.capital.reserve_safety_orders,
    bufferPercent: props.capital.budget_buffer_pct,
    dynamicDcaEnabled: props.dynamicDcaEnabled,
    openTrades: openTrades.status === 'OPEN' && openTrades.hasReceivedData
        ? openTrades.data : null,
}))
const numberFormat = new Intl.NumberFormat('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
})
function quote(value: number): string {
    return `${numberFormat.format(value)} ${(props.quoteCurrency ?? '').toUpperCase()}`.trim()
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
.capital-field {
    width: 100%;
    min-width: 0;
}

.capital-help {
    margin: 8px 0 0;
    color: var(--mw-color-text-secondary);
    font-size: 14px;
    line-height: 1.5;
    overflow-wrap: anywhere;
}

.capital-estimate {
    margin-top: 12px;
    color: var(--mw-color-text-primary);
    font-size: 14px;
    line-height: 1.5;
    overflow-wrap: anywhere;
}

.capital-estimate strong {
    font-family: var(--mw-font-mono);
    font-weight: 450;
    font-variant-numeric: tabular-nums;
}
</style>
