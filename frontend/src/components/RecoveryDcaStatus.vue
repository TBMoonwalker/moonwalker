<template>
    <section v-if="visible" class="recovery-status" aria-label="Recovery DCA status">
        <div class="recovery-heading">
            <span>Recovery DCA</span>
            <span class="recovery-count">{{ shadow ? 'Shadow' : orderLabel }}</span>
        </div>
        <p class="recovery-title" :class="{ 'needs-attention': status.warning }" role="status">
            {{ status.title }}
        </p>
        <dl v-if="!shadow" class="recovery-prices">
            <div><dt>Current</dt><dd>{{ price(current) }}</dd></div>
            <div><dt>Trigger ≤ <span>{{ quote }}</span></dt><dd>{{ price(trigger) }}</dd></div>
        </dl>
        <p class="recovery-support">{{ status.detail }}</p>
        <p v-if="sizingCurrent" class="recovery-estimate">
            Estimated buy {{ number(decision.final_quote).toFixed(2) }} {{ quote }}
            · Projected TP {{ price(number(decision.projected_tp_price)) }}
        </p>
        <details class="recovery-explanation" @click.stop>
            <summary>How this is calculated</summary>
            <p v-if="!shadow && spacing > 0">
                Required drop: {{ percent(spacing) }} from the last buy at
                {{ price(reference) }} {{ quote }}.
                <template v-if="atr > 0 && multiplier > 0">
                    Spacing uses {{ multiplier }} × {{ percent(atr) }} reference ATR,
                    with a {{ percent(number(policy.minimum_spacing_percent)) }} minimum
                    and the saved step scale for later orders.
                </template>
            </p>
            <p>{{ shadow ? 'Recovery calculations are for comparison only; legacy DCA controls actual buys.' : 'The price gate, a fresh strategy signal, sizing and execution checks must all pass before a buy.' }}</p>
            <p>Recovery settings are saved when this deal opens.</p>
        </details>
    </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useNow } from '@vueuse/core'
import { useSharedConfigSnapshot } from '../control-center/configSnapshotStore'

type RecoveryTrade = {
    symbol: string
    current_price?: number | string
    automation_paused?: boolean
    so_count?: number
    safetyorder?: unknown[]
    dca_sizing_mode?: string | null
    dca_policy_json?: string | null
    dca_reference_price?: number
    dca_reference_atr_percent?: number
    dca_next_trigger_price?: number
    dca_last_decision_json?: string | null
}
const props = defineProps<{ trade: RecoveryTrade }>()
const config = useSharedConfigSnapshot()
const now = useNow({ interval: 5_000 })
const visible = computed(() => ['recovery_target', 'recovery_shadow'].includes(props.trade.dca_sizing_mode ?? ''))
const shadow = computed(() => props.trade.dca_sizing_mode === 'recovery_shadow')
const decision = computed(() => parseObject(props.trade.dca_last_decision_json))
const policy = computed(() => parseObject(props.trade.dca_policy_json))
const current = computed(() => number(props.trade.current_price))
const trigger = computed(() => number(props.trade.dca_next_trigger_price))
const reference = computed(() => number(props.trade.dca_reference_price))
const atr = computed(() => number(props.trade.dca_reference_atr_percent))
const multiplier = computed(() => number(policy.value.spacing_atr_multiplier))
const spacing = computed(() => reference.value > 0 && trigger.value > 0
    ? Math.max(0, (1 - trigger.value / reference.value) * 100) : 0)
const quote = computed(() => props.trade.symbol.split('/')[1] ?? '')
const filled = computed(() => props.trade.so_count ?? props.trade.safetyorder?.length ?? 0)
const maximum = computed(() => config.snapshot.value?.mstc == null ? null : number(config.snapshot.value.mstc))
const orderLabel = computed(() => maximum.value !== null
    ? `SO ${Math.min(filled.value + 1, maximum.value)} / ${maximum.value}`
    : `Next SO ${filled.value + 1}`)
// Freshness is anchored to the local time this card first observed a *changed*
// heartbeat, never to the server's evaluated_at_ms. A skewed client clock
// therefore cannot mark a live recovery evaluation as stale, and the 30s / 90s
// backend window still drives expiry by observation.
const lastHeartbeatAt = ref(0)
watch(
    () => number(decision.value.evaluated_at_ms),
    (stamp) => {
        lastHeartbeatAt.value = stamp > 0 ? now.value.getTime() : 0
    },
    { immediate: true },
)

const fresh = computed(() => {
    const stamp = number(decision.value.evaluated_at_ms)
    if (stamp <= 0) {
        return false
    }
    return now.value.getTime() - lastHeartbeatAt.value < 90_000
        && number(decision.value.trigger_price) === trigger.value
        && number(decision.value.reference_price) === reference.value
})
const sizingCurrent = computed(() => !shadow.value && fresh.value && !props.trade.automation_paused
    && config.snapshot.value?.dca !== false
    && (maximum.value === null || filled.value < maximum.value)
    && current.value > 0 && current.value <= trigger.value
    && current.value === number(decision.value.current_price)
    && ['target_recovery', 'budget_capped'].includes(String(decision.value.reason))
    && number(decision.value.final_quote) > 0 && number(decision.value.projected_tp_price) > 0)

const status = computed(() => {
    const result = (title: string, detail: string, warning = false) => ({ title, detail, warning })
    if (shadow.value) return result('Comparison only', 'Legacy DCA controls safety orders for this deal.')
    if (props.trade.automation_paused) return result('Automation paused', 'Automatic safety orders are paused for this deal.')
    if (config.snapshot.value?.dca === false) return result('DCA disabled', 'Automatic safety orders are disabled.')
    if (maximum.value !== null && filled.value >= maximum.value)
        return result('Safety-order limit reached', `${filled.value} safety orders filled; limit ${maximum.value}.`)
    if (!fresh.value || current.value <= 0 || trigger.value <= 0)
        return result('Updating status', 'Waiting for a recent recovery evaluation.')
    const reason = String(decision.value.reason ?? '')
    if (reason === 'missing_deal_budget')
        return result('Safety order blocked by budget', 'This deal has no positive recovery budget.', true)
    if (current.value > trigger.value) {
        const distance = (1 - trigger.value / current.value) * 100
        return result('Waiting for a lower price', `Another ${percent(distance)} drop to reach the price gate.`)
    }
    if (reason === 'waiting_for_atr_spacing')
        return result('Updating status', 'Price condition met; waiting for the next evaluation.')
    if (['recovery_signal_not_matched', 'recovery_signal_unchanged'].includes(reason))
        return result('Waiting for strategy confirmation', 'Price condition met; no fresh qualifying buy signal at the last check.')
    // Sizing diagnostics describe a specific candidate price, not a live quote.
    if (number(decision.value.current_price) !== current.value)
        return result('Updating status', 'Price changed; waiting for a new sizing check.')
    if (reason === 'tp_already_reachable')
        return result('No extra buy needed', `TP needs ${percent(number(decision.value.current_recovery_percent))} rebound; target allows ${percent(number(decision.value.target_recovery_percent))}.`)
    if (reason === 'deal_budget_exhausted')
        return result('Safety order blocked by budget', `Remaining deal budget: ${number(decision.value.remaining_deal_quote).toFixed(2)} ${quote.value}.`, true)
    if (reason === 'below_exchange_minimum')
        return result('Buy amount below exchange minimum', `Available buy ${number(decision.value.final_quote).toFixed(2)} ${quote.value}; minimum ${number(decision.value.minimum_order_quote).toFixed(2)} ${quote.value}.`, true)
    if (reason === 'insufficient_tp_improvement')
        return result('Budget-limited buy would help too little', `TP improvement ${number(decision.value.tp_improvement_percent).toFixed(2)} percentage points; minimum ${number(policy.value.minimum_tp_improvement_percent).toFixed(2)}.`, true)
    if (sizingCurrent.value)
        return result('Buy sized; execution not confirmed', 'Balance and execution checks still apply. This is an estimate.')
    if (['invalid_trade_state', 'target_not_solvable'].includes(reason))
        return result('Unable to size a safety order', 'The last calculation could not produce a valid recovery buy.', true)
    return result('Updating status', 'Waiting for a recent recovery decision.')
})

function parseObject(raw?: string | null): Record<string, unknown> {
    try {
        const parsed = JSON.parse(raw ?? '{}')
        return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {}
    } catch { return {} }
}
function number(value: unknown): number {
    const parsed = typeof value === 'number' || typeof value === 'string' ? Number(value) : NaN
    return Number.isFinite(parsed) ? parsed : 0
}
function percent(value: number): string {
    return value > 0 && value < 0.01 ? '<0.01%' : `${value.toFixed(2)}%`
}
function price(value: number): string {
    return value > 0 ? new Intl.NumberFormat('en-US', { maximumSignificantDigits: 8 }).format(value) : '—'
}
</script>

<style scoped>
.recovery-status {
    border-bottom: 1px solid var(--mw-color-border);
    margin-bottom: 16px;
    padding-bottom: 16px;
    overflow-wrap: anywhere;
}
.recovery-heading { display: flex; justify-content: space-between; gap: 8px; font-weight: 600; }
.recovery-count { color: var(--mw-color-text-muted); font-size: 12px; font-weight: 400; }
.recovery-title { margin: 12px 0 8px; font-size: 16px; font-weight: 600; }
.needs-attention { color: var(--mw-color-text-primary); background: color-mix(in srgb, var(--mw-color-warning) 14%, var(--mw-color-surface-panel)); padding: 8px; border-radius: var(--mw-radius-sm); }
.recovery-prices { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin: 0; }
dt { color: var(--mw-color-text-muted); font-size: 12px; }
dd { margin: 0; font-family: var(--mw-font-mono); font-size: 14px; font-variant-numeric: tabular-nums; }
.recovery-support, .recovery-estimate { margin: 8px 0 0; font-size: 14px; color: var(--mw-color-text-secondary); }
.recovery-estimate { font-family: var(--mw-font-mono); }
.recovery-explanation { margin-top: 4px; color: var(--mw-color-text-secondary); font-size: 14px; }
summary { cursor: pointer; min-height: 44px; align-content: center; text-decoration: underline; text-underline-offset: 3px; }
summary:focus-visible { outline: 2px solid var(--mw-color-primary); outline-offset: 2px; border-radius: 4px; }
.recovery-explanation p { margin: 8px 0 0; }
</style>
