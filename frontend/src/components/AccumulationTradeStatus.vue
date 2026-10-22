<script setup lang="ts">
import { computed } from 'vue'
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
</script>

<template>
  <section class="accumulation-trade-status" :aria-label="`${symbol} accumulation`">
    <AccumulationOutlook v-if="detail" :detail="detail" :fresh="fresh" />
    <p v-else role="status">Loading accumulation status…</p>
    <n-button v-if="!fresh" :loading="panel.loading.value" :disabled="busy" @click="panel.refreshDetail()">Refresh status</n-button>
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-if="notice" role="status">{{ notice }}</p>
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
          <n-button :disabled="disabled || !panel.targetVersion.value || panel.targetVersion.value === detail.strategy_version_id" @click="panel.prepare('switch_strategy')">Use strategy</n-button>
        </div>
      </details>
      <n-button v-for="action in controls" :key="action" :disabled="disabled" @click="panel.prepare(action)">{{ accumulationActionLabels[action] }}</n-button>
      <n-button v-if="actions.includes('close')" :disabled="disabled" @click="panel.prepare('close')">Sell and close</n-button>
      <RouterLink v-if="needsRepair" :to="{ name: 'controlCenter', query: { mode: 'utilities' }, hash: '#accumulation-controls' }">Resolve accumulation issue</RouterLink>
    </div>
    <div v-if="draft && detail" class="accumulation-confirmation" role="region" :aria-label="`Review ${accumulationActionLabels[draft.action].toLowerCase()}`">
      <p>{{ accumulationActionCopy(draft.action, symbol) }}</p>
      <p v-if="draft.target_version_id">New strategy: {{ strategyOptions.find(option => option.value === draft!.target_version_id)?.label }}</p>
      <n-button type="primary" :disabled="disabled || draft.expected_revision !== detail.revision || !actions.includes(draft.action)" :loading="busy" @click="panel.submit()">Confirm {{ accumulationActionLabels[draft.action].toLowerCase() }}</n-button>
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
p { margin: 0; color: var(--mw-color-text-secondary); }
@media (max-width: 767px) {
  .accumulation-trade-status :deep(.n-button), .accumulation-trade-status :deep(.n-base-selection), summary { min-height: 44px; }
  .accumulation-trade-controls > span, .strategy-change { flex-basis: 100%; }
}
</style>
