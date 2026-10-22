<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import AccumulationOutlook from './AccumulationOutlook.vue'
import { useAccumulationPanel } from '../composables/useAccumulationPanel'
import { accumulationActionCopy, accumulationActionLabels } from '../helpers/accumulation'
import type { AccumulationAction } from '../types/accumulation'

const props = defineProps<{ symbol: string }>()
const panel = useAccumulationPanel(props.symbol)
const { detail, fresh, actions, disabled, busy, error, notice, draft, uncertain } = panel
const strategyOptions = computed(() => panel.strategies.value.map(version => ({
  label: `${version.name} · v${version.version} · ${version.parameters.timeframe}`, value: version.id,
})))
const strategy = computed(() => strategyOptions.value.find(version => version.value === detail.value?.strategy_version_id)?.label ?? detail.value?.strategy_slug ?? 'Strategy unavailable')
const controls = computed(() => (['pause', 'resume', 'retry_close'] as AccumulationAction[]).filter(action => actions.value.includes(action)))
const needsRepair = computed(() => detail.value?.account_matches === false || detail.value?.holding_integrity === 'invalid' || detail.value?.inventory_restore_required || detail.value?.quarantined_orders?.length || detail.value?.quarantined_commands?.length || detail.value?.settled_commands?.length)
const partialSaleOpen = ref(false)
const root = ref<HTMLElement | null>(null)
const reviewHeading = ref<HTMLElement | null>(null)
let initiator: HTMLElement | null = null
function prepare(action: AccumulationAction, event: Event) {
  initiator = event.currentTarget as HTMLElement | null
  panel.prepare(action)
}
async function restoreFocus() {
  await nextTick()
  if (initiator?.isConnected && !initiator.matches(':disabled')) initiator.focus()
  else root.value?.querySelector<HTMLElement>('h3')?.focus()
}
watch(() => draft.value?.operation_id, async (id, previous) => {
  if (id) { await nextTick(); reviewHeading.value?.focus() }
  else if (previous && !busy.value) void restoreFocus()
})
watch(busy, (sending, previous) => { if (previous && !sending) void restoreFocus() })
async function openPartialSale() {
  partialSaleOpen.value = true
  await nextTick()
  document.getElementById(`sale-${props.symbol}`)?.focus()
}
</script>

<template>
  <section ref="root" class="accumulation-trade-status" :aria-label="`${symbol} accumulation`">
    <AccumulationOutlook v-if="detail" :detail="detail" :fresh="fresh" />
    <p v-else role="status">Loading accumulation status…</p>
    <n-button v-if="!fresh" :loading="panel.loading.value" :disabled="busy" @click="panel.refreshDetail()">Refresh status</n-button>
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-if="notice" role="status">{{ notice }}</p>
    <p v-if="panel.pendingRequest.value && panel.pendingRequest.value.symbol !== symbol" role="status">Resolve the pending request for {{ panel.pendingRequest.value.symbol }} before starting another action.</p>
    <div v-if="uncertain" role="alert">
      <p>Unconfirmed request: {{ accumulationActionLabels[uncertain.action] }}.</p>
      <n-button :disabled="busy || !panel.available.value" :loading="busy" @click="panel.submit()">Retry same request</n-button>
    </div>
    <div v-if="detail" class="accumulation-trade-controls">
      <span>{{ strategy }}</span>
      <details v-if="actions.includes('switch_strategy')" class="strategy-change">
        <summary>Change strategy</summary>
        <div class="strategy-fields">
          <label :for="`strategy-${symbol}`">Accumulation strategy</label>
          <n-select filterable v-model:value="panel.targetVersion.value" :input-props="{ id: `strategy-${symbol}`, 'aria-label': 'Accumulation strategy' }" :options="strategyOptions" :disabled="disabled" placeholder="Select a saved strategy" />
          <n-button v-if="panel.strategyCursor.value" :disabled="panel.strategyLoading.value" @click="panel.loadStrategies(true)">Load more strategies</n-button>
          <p v-if="panel.strategyError.value" role="alert">{{ panel.strategyError.value }}</p>
          <n-button :disabled="disabled || !panel.targetVersion.value || panel.targetVersion.value === detail.strategy_version_id" @click="prepare('switch_strategy', $event)">Use strategy</n-button>
        </div>
      </details>
      <n-button v-for="action in controls" :key="action" :disabled="disabled" @click="prepare(action, $event)">{{ accumulationActionLabels[action] }}</n-button>
      <n-button v-if="actions.includes('sell_partial')" :disabled="disabled" :aria-expanded="partialSaleOpen" @click="openPartialSale">Sell part</n-button>
      <n-button v-if="actions.includes('close')" :disabled="disabled" @click="prepare('close', $event)">Sell and close</n-button>
      <RouterLink v-if="needsRepair" :to="{ name: 'controlCenter', query: { mode: 'utilities', symbol }, hash: '#accumulation-controls' }">Resolve accumulation issue</RouterLink>
    </div>
    <div v-if="partialSaleOpen && actions.includes('sell_partial')" class="strategy-fields">
      <label :for="`sale-${symbol}`">Partial sale quantity · {{ symbol.split('/')[0] }}</label>
      <n-input v-model:value="panel.quantity.value" :disabled="disabled" :input-props="{ id: `sale-${symbol}`, inputmode: 'decimal' }" />
      <n-button :disabled="disabled" @click="prepare('sell_partial', $event)">Review partial sale</n-button>
      <n-button :disabled="busy || !!draft" @click="partialSaleOpen = false">Hide sale form</n-button>
    </div>
    <div v-if="draft && detail" class="accumulation-confirmation" role="region" :aria-label="`Review ${accumulationActionLabels[draft.action].toLowerCase()}`">
      <h4 ref="reviewHeading" tabindex="-1">Review {{ accumulationActionLabels[draft.action].toLowerCase() }} · {{ symbol }}</h4>
      <p>{{ accumulationActionCopy(draft.action, symbol) }}</p>
      <p v-if="draft.quantity">Quantity: {{ draft.quantity }} {{ symbol.split('/')[0] }}</p>
      <p v-if="draft.target_version_id">New strategy: {{ strategyOptions.find(option => option.value === draft!.target_version_id)?.label }}</p>
      <p v-if="panel.confirmBlockedReason.value" role="status">{{ panel.confirmBlockedReason.value }}</p>
      <n-button type="primary" :disabled="!!panel.confirmBlockedReason.value" :loading="busy" @click="panel.submit()">Confirm {{ accumulationActionLabels[draft.action].toLowerCase() }}</n-button>
      <n-button :disabled="busy" @click="panel.draft.value = null">Cancel</n-button>
    </div>
  </section>
</template>

<style scoped>
.accumulation-trade-status { display: grid; gap: 12px; min-width: 0; }
.accumulation-trade-status :deep(.outlook-message) { border-left: 0; padding-left: 0; }
.accumulation-trade-status :deep(h3) { font-size: 20px; }
.accumulation-trade-controls { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; font-size: 14px; }
.accumulation-trade-controls > span { margin-right: auto; color: var(--mw-color-text-secondary); }
.strategy-change { min-width: 0; }
.strategy-change[open] { flex-basis: 100%; order: 1; }
summary { cursor: pointer; padding-block: 12px; color: var(--mw-color-text-primary); }
.strategy-fields { display: grid; gap: 8px; width: 100%; max-width: 480px; padding-block: 8px; }
.accumulation-confirmation { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; border-top: 1px solid var(--mw-color-border); padding-top: 16px; }
.accumulation-confirmation p { flex-basis: 100%; margin: 0; }
.accumulation-confirmation h4 { flex-basis: 100%; margin: 0; font-size: 16px; }
.accumulation-confirmation h4:focus-visible { outline: var(--mw-focus-ring); outline-offset: var(--mw-focus-offset); }
p { margin: 0; color: var(--mw-color-text-secondary); }
@media (max-width: 767px) {
  .accumulation-trade-status :deep(.n-button), .accumulation-trade-status :deep(.n-base-selection), .accumulation-trade-status :deep(.n-input), summary { min-height: 44px; }
  .accumulation-trade-controls > span, .strategy-change { flex-basis: 100%; }
}
</style>
