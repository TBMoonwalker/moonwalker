<script setup lang="ts">
import { computed } from 'vue'
import type { useAccumulationPanel } from '../composables/useAccumulationPanel'
import { accumulationReason } from '../helpers/accumulation'
const props = defineProps<{ context: ReturnType<typeof useAccumulationPanel> }>()
const panel = props.context
const portfolio = computed(() => panel.portfolio.value)
const busy = computed(() => panel.busy.value)
</script>
<template>
  <div v-if="panel.visible.value && (panel.rows.value.length || portfolio?.holding_count)" class="accumulation-portfolio" aria-label="Accumulation portfolio accounting">
    <details v-if="portfolio" class="accumulation-history" :open="portfolio.unverified_holding_count > 0 || portfolio.by_quote.some(group => group.unknown_cost_count > 0)">
      <summary>All accumulation holdings · {{ portfolio.holding_count }}</summary>
    <div v-if="portfolio" aria-label="Accumulation inventory summary">
      <p>{{ portfolio.holding_count }} managed holdings. Amounts cover all accumulation holdings, including symbols outside the current page.</p>
      <dl class="accumulation-values">
        <div v-for="group in portfolio.by_quote" :key="group.quote">
          <dt>Remaining cost · {{ group.quote }}</dt>
          <dd>{{ group.remaining_cost ?? 'Unknown' }}</dd>
          <p v-if="group.unknown_cost_count">Known subtotal: {{ group.known_remaining_cost }} {{ group.quote }}; {{ group.unknown_cost_count }} holdings have unknown cost.</p>
        </div>
      </dl>
      <p>Cost is not market value or net profit. Refresh valuation below for market value and verified returns.</p>
      <n-alert v-if="portfolio.unverified_holding_count" type="warning">{{ portfolio.unverified_holding_count }} holdings need ownership repair. Their recorded costs remain included.</n-alert>
    </div>
    </details>
    <details class="accumulation-history">
      <summary>Accumulation value and returns</summary>
      <p>Market value uses fresh bids before any future sale fee. Returns include recorded execution fees; unknown historical fees, ownership or basis keep returns unavailable. Quote currencies stay separate.</p>
      <n-button :loading="panel.performanceLoading.value" :disabled="busy || panel.performanceLoading.value" @click="panel.loadPerformance()">Refresh valuation</n-button>
      <p v-if="panel.performanceError.value" role="alert">{{ panel.performanceError.value }}</p>
      <template v-if="panel.performance.value">
        <p>Observed: {{ new Date(panel.performance.value.observed_at_ms).toISOString() }}. This is a snapshot; refresh for a current valuation.</p>
        <p v-if="panel.performance.value.reason">{{ accumulationReason(panel.performance.value.reason) }}</p>
        <p v-if="!panel.performance.value.by_quote.length">No managed capital or executed accumulation history.</p>
        <div v-for="group in panel.performance.value.by_quote" :key="group.quote">
          <strong>{{ group.quote }}</strong>
          <dl class="accumulation-values">
            <div><dt>Market value</dt><dd>{{ group.market_value ?? 'Unavailable' }}</dd></div>
            <div><dt>Realized return</dt><dd>{{ group.realized ?? 'Unknown' }}</dd></div>
            <div><dt>Unrealized return</dt><dd>{{ group.unrealized ?? 'Unknown' }}</dd></div>
            <div><dt>Total return</dt><dd>{{ group.total_return ?? 'Unknown' }}</dd></div>
          </dl>
          <p v-if="!group.complete">{{ group.unknown_deal_count }} holding histories lack complete evidence. These returns cannot be verified.</p>
        </div>
      </template>
    </details>

  </div>
</template>
<style scoped>
.accumulation-portfolio { min-width: 0; margin-top: 16px; font-size: 14px; }
summary { cursor: pointer; min-height: 44px; align-content: center; }
summary:focus-visible { outline: var(--mw-focus-ring); outline-offset: var(--mw-focus-offset); }
.accumulation-values { display: grid; gap: 8px; margin: 12px 0; }
dt, p { color: var(--mw-color-text-secondary); }
dd { margin: 0; font-family: var(--mw-font-mono); overflow-wrap: anywhere; }
@media (max-width: 767px) { .accumulation-portfolio :deep(.n-button) { min-height: 44px; } }
</style>
