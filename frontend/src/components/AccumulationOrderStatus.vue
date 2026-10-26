<script setup lang="ts">
import { computed } from 'vue'
import type { AccumulationStatus } from '../types/accumulation'
import { accumulationPendingStatus, accumulationIndicativeCondition } from '../helpers/accumulationPresentation'
const props = defineProps<{ status?: AccumulationStatus; fresh: boolean }>()
const condition = computed(() => {
  const row = props.status
  const value = row?.wait_condition
  if (!props.fresh || !row || row.state !== 'enabled' || row.explicitly_paused || row.account_matches === false || row.holding_integrity === 'invalid' || row.inventory_restore_required || !value || value.reason !== row.runtime_wait_reason || !['WAIT_BASELINE', 'WAIT_DEPTH', 'WAIT_DECLINE', 'WAIT_REARM', 'WAIT_NEW_CANDLE'].includes(value.reason) || !Array.isArray(value.levels) || !value.levels.every(level => Number(level.target_price) > 0 && Number.isFinite(Number(level.target_price)) && Number.isFinite(Number(level.change_percent)))) return null
  return value
})
const indicative = computed(() => accumulationIndicativeCondition(condition.value))
const title = computed(() => condition.value && ['WAIT_BASELINE', 'WAIT_NEW_CANDLE'].includes(condition.value.reason)
  ? `Waiting for the next ${condition.value.timeframe} close`
  : props.status ? accumulationPendingStatus(props.status, props.fresh) : 'Status unavailable · open trade details')
function movement(value: string) {
  const amount = Math.abs(Number(value))
  if (amount === 0) return 'Lower close'
  return `${Number(value) > 0 ? 'Rise' : 'Fall'} ≈ ${amount < 0.01 ? '<0.01' : amount.toFixed(2)}%`
}
</script>

<template>
  <div class="accumulation-order-status" role="status">
    <span>{{ title }}</span>
    <span v-if="condition && !condition.levels.length" class="trade-cell-sub">Next close: {{ new Date(condition.next_close_ms).toISOString().replace('T', ' ').slice(0, 16) }} UTC</span>
    <span v-if="indicative" class="trade-cell-sub">Indicative: {{ movement(indicative.level.change_percent) }} · {{ indicative.level.direction === 'below' ? '<' : '≤' }} {{ Number(indicative.level.target_price).toLocaleString(undefined, { maximumSignificantDigits: 10 }) }} {{ status?.symbol.split('/')[1] }}</span>
    <span v-for="level in condition?.levels" :key="level.kind" class="trade-cell-sub"><template v-if="level.kind === 'recovery_then_correction'">Recovery reset: </template>{{ movement(level.change_percent) }} · {{ level.direction === 'at_or_above' ? '≥' : '≤' }} {{ Number(level.target_price).toLocaleString(undefined, { maximumSignificantDigits: 10 }) }} {{ status?.symbol.split('/')[1] }}<template v-if="level.kind === 'recovery_then_correction'"> · no buy; correction required</template></span>
  </div>
</template>

<style scoped>
.accumulation-order-status { display: grid; gap: 4px; text-align: left; font-size: 14px; overflow-wrap: anywhere; }
.trade-cell-sub { color: var(--mw-color-text-secondary); font-size: 12px; }
</style>
