<script setup lang="ts">
import { computed } from 'vue'
import type { AccumulationDetail } from '../types/accumulation'
import { accumulationOutlook } from '../helpers/accumulationPresentation'

const props = defineProps<{ detail: AccumulationDetail; fresh: boolean; compact?: boolean }>()
const outlook = computed(() => accumulationOutlook(props.detail, props.fresh))
const hasAction = computed(() => accumulationOutlook(props.detail, true).action)
const condition = computed(() => {
  const value = props.detail.wait_condition
  if (!props.fresh || props.detail.state !== 'enabled' || props.detail.explicitly_paused ||
      props.detail.account_matches === false || props.detail.holding_integrity === 'invalid' ||
      props.detail.inventory_restore_required || props.detail.quarantined_orders?.length ||
      props.detail.quarantined_commands?.length || props.detail.operations.some(operation => operation.status === 'pending') ||
      !value || value.reason !== props.detail.runtime_wait_reason || !Array.isArray(value.levels) ||
      !value.levels.every(level => Number.isFinite(Number(level.target_price)) && Number(level.target_price) > 0 && Number.isFinite(Number(level.change_percent)))) return null
  return value
})
const buyLevels = computed(() => condition.value?.levels.filter(level => level.kind !== 'recovery_then_correction') ?? [])
const recoveryLevels = computed(() => condition.value?.levels.filter(level => level.kind === 'recovery_then_correction') ?? [])
const quote = computed(() => props.detail.symbol.split('/')[1] ?? '')
const heading = computed(() => condition.value ? condition.value.price_basis === 'ask' ? 'Waiting for buy price' : recoveryLevels.value.length && !buyLevels.value.length ? 'Waiting for a fresh dip' : condition.value.levels.length ? props.detail.holding ? 'Waiting for next buy' : 'Waiting for entry' : ['WAIT_BASELINE', 'WAIT_NEW_CANDLE'].includes(condition.value.reason) ? `Waiting for the next ${condition.value.timeframe} close` : outlook.value.title : outlook.value.title)
function price(value: string) {
  return Number(value).toLocaleString(undefined, { maximumSignificantDigits: 10 })
}
function movement(value: string) {
  const amount = Math.abs(Number(value))
  if (amount === 0) return 'A lower close'
  const percent = amount < 0.01 ? '<0.01' : amount.toFixed(2)
  return `≈ ${percent}% ${Number(value) > 0 ? 'rise' : 'fall'}`
}
</script>

<template>
  <div class="accumulation-outlook" :class="{ compact }" :data-tone="outlook.tone">
    <div class="outlook-now">
      <div class="outlook-message" role="status">
        <span v-if="!compact" class="outlook-label">{{ detail.symbol }} · Current state</span>
        <h3 tabindex="-1">{{ heading }}</h3>
        <template v-if="condition">
          <ul v-if="buyLevels.length" class="wait-levels" aria-label="Current buy conditions">
            <li v-for="(level, index) in buyLevels" :key="level.kind">
              <span v-if="index" class="wait-or">or</span>
              <strong>{{ movement(level.change_percent) }}</strong>
              <span :title="level.target_price">{{ level.direction === 'below' ? 'below' : level.direction === 'at_or_below' ? 'to ≤' : 'to ≥' }} ≈ {{ price(level.target_price) }} {{ quote }}</span>
            </li>
          </ul>
          <p v-if="condition.reason === 'WAIT_BASELINE'">No price target yet. Waiting for the next completed candle to evaluate a new buy signal; a buy is not guaranteed.</p>
          <p v-else-if="!condition.levels.length">{{ outlook.description }}</p>
          <p v-if="!condition.levels.length">Next close: {{ new Date(condition.next_close_ms).toISOString().replace('T', ' ').slice(0, 16) }} UTC</p>
          <div v-if="recoveryLevels.length" class="recovery-condition">
            <h4>Recovery needed before another dip buy</h4>
            <p v-for="level in recoveryLevels" :key="level.kind" :title="level.target_price">{{ movement(level.change_percent) }} to ≥ ≈ {{ price(level.target_price) }} {{ quote }}</p>
            <p class="wait-note">No buy on this rise. A fresh correction must follow.</p>
          </div>
          <p v-if="condition.levels.length" class="wait-note">{{ condition.price_basis === 'ask' ? 'From the latest ask' : `From the latest completed ${condition.timeframe} close` }} · levels update with market data</p>
        </template>
        <p v-else>{{ outlook.description }}</p>
      </div>
      <div v-if="hasAction" class="outlook-next">
        <slot />
      </div>
    </div>
  </div>
</template>

<style scoped>
.accumulation-outlook { min-width: 0; border-block: 1px solid var(--mw-color-border); }
.outlook-now { display: flex; justify-content: space-between; align-items: center; gap: 24px; padding-block: 16px; }
.outlook-message { min-width: 0; }
[data-tone="warning"] .outlook-message { border-color: var(--mw-color-warning); }
[data-tone="default"] .outlook-message { border-color: var(--mw-color-border-strong); }
.outlook-label { font-size: 14px; color: var(--mw-color-text-secondary); }
h3 { margin: 8px 0; font: 600 24px/1.25 var(--mw-font-display); color: var(--mw-color-text-primary); }
p { margin: 0; font-size: 16px; line-height: 1.5; color: var(--mw-color-text-secondary); }
.outlook-next { display: grid; align-content: start; justify-items: start; gap: 8px; }
.wait-levels { display: flex; flex-wrap: wrap; gap: 16px 32px; list-style: none; padding: 0; margin: 12px 0 0; }
.wait-levels li { display: grid; align-content: start; gap: 4px; }
.wait-levels strong { color: var(--mw-color-text-primary); font: 500 20px var(--mw-font-mono); }
.wait-levels li > span { font-size: 16px; color: var(--mw-color-text-secondary); }
.wait-levels .wait-or { font-size: 14px; }
.recovery-condition { margin-top: 16px; padding-top: 12px; border-top: 1px solid var(--mw-color-border); }
.recovery-condition h4 { margin: 0 0 4px; font-size: 14px; font-weight: 600; color: var(--mw-color-text-secondary); }
.wait-note, .wait-levels .wait-note { margin-top: 8px; font-size: 14px; color: var(--mw-color-text-secondary); }
.compact { border-top: 0; margin-bottom: 16px; }
.compact .outlook-now { padding-top: 0; gap: 12px; }
.compact h3 { margin-top: 0; font-size: 16px; }
.compact p, .compact .wait-levels li > span { font-size: 14px; }
.compact .wait-levels { gap: 12px; }
.compact .wait-levels strong { font-size: 16px; }
@media (max-width: 767px) {
  .outlook-now { flex-direction: column; align-items: stretch; gap: 16px; }
  .outlook-next { padding-left: 16px; }
  h3 { font-size: 20px; }
}
</style>
