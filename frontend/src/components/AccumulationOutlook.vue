<script setup lang="ts">
import { computed } from 'vue'
import type { AccumulationDetail, AccumulationStrategy } from '../types/accumulation'
import { accumulationOutlook } from '../helpers/accumulationPresentation'

const props = defineProps<{ detail: AccumulationDetail; fresh: boolean; strategy?: AccumulationStrategy }>()
const outlook = computed(() => accumulationOutlook(props.detail, props.fresh))
</script>

<template>
  <div class="accumulation-outlook" :data-tone="outlook.tone">
    <div class="outlook-now">
      <div class="outlook-message" role="status">
        <span class="outlook-label">{{ detail.symbol }} · Current state</span>
        <h3>{{ outlook.title }}</h3>
        <p>{{ outlook.description }}</p>
      </div>
      <div class="outlook-next">
        <span class="outlook-label">Next step</span>
        <p>{{ outlook.next }}</p>
        <slot />
      </div>
    </div>
    <ol class="accumulation-cycle" aria-label="How accumulation works">
      <li>
        <span class="cycle-number" aria-hidden="true">1</span>
        <div><strong>Validate entry</strong><span>{{ detail.observations_initialized ? 'Entry checked' : 'Required before buying' }}</span></div>
      </li>
      <li>
        <span class="cycle-number" aria-hidden="true">2</span>
        <div><strong>Watch the market</strong><span>{{ strategy ? `Completed ${strategy.parameters.timeframe} candles` : 'Completed strategy candles' }}</span></div>
      </li>
      <li>
        <span class="cycle-number" aria-hidden="true">3</span>
        <div><strong>Accumulate on dips</strong><span>Buy within available budget</span></div>
      </li>
    </ol>
    <p v-if="strategy" class="strategy-summary">{{ strategy.name }} · v{{ strategy.version }} · {{ strategy.parameters.timeframe }}</p>
    <div class="accumulation-expectation">
      <span><strong>Buy sizing</strong> Deeper qualifying dips can use more budget.</span>
      <span><strong>Exit</strong> Sales require your action.</span>
    </div>
    <p v-if="!detail.observations_initialized" class="entry-expectation">{{ detail.entry?.source === 'csv' ? 'CSV stages your existing coins for validation.' : 'ASAP registers the symbol.' }} Entry validation does not force an immediate buy.</p>
  </div>
</template>

<style scoped>
.accumulation-outlook { min-width: 0; border-block: 1px solid var(--mw-color-border); }
.outlook-now { display: grid; grid-template-columns: minmax(0, 3fr) minmax(0, 2fr); gap: 32px; padding-block: 24px; }
.outlook-message { border-left: 3px solid var(--mw-color-info); padding-left: 16px; }
[data-tone="warning"] .outlook-message { border-color: var(--mw-color-warning); }
[data-tone="default"] .outlook-message { border-color: var(--mw-color-border-strong); }
.outlook-label { font-size: 14px; color: var(--mw-color-text-secondary); }
h3 { margin: 8px 0; font: 600 24px/1.25 var(--mw-font-display); color: var(--mw-color-text-primary); }
p { margin: 0; font-size: 16px; line-height: 1.5; color: var(--mw-color-text-secondary); }
.outlook-next { display: grid; align-content: start; justify-items: start; gap: 8px; }
.accumulation-cycle { list-style: none; display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 24px; margin: 0; padding: 16px 0; border-top: 1px solid var(--mw-color-border); }
.accumulation-cycle li { display: flex; align-items: flex-start; gap: 12px; min-width: 0; }
.cycle-number { display: grid; place-items: center; flex: 0 0 32px; height: 32px; border: 1px solid var(--mw-color-border-strong); border-radius: 50%; color: var(--mw-color-text-secondary); font: 500 14px var(--mw-font-mono); }
.accumulation-cycle strong { display: block; color: var(--mw-color-text-primary); font-weight: 600; font-size: 16px; }
.accumulation-cycle div > span { display: block; margin-top: 4px; color: var(--mw-color-text-secondary); font-size: 14px; }
.accumulation-expectation { display: flex; flex-wrap: wrap; gap: 8px 32px; padding-block: 16px; border-top: 1px solid var(--mw-color-border); font-size: 14px; color: var(--mw-color-text-secondary); }
.accumulation-expectation strong { margin-right: 8px; font-weight: 600; color: var(--mw-color-text-primary); }
.entry-expectation { padding-bottom: 16px; font-size: 14px; }
.strategy-summary { padding-bottom: 16px; font-size: 14px; color: var(--mw-color-text-primary); }
@media (max-width: 767px) {
  .outlook-now { grid-template-columns: 1fr; gap: 24px; padding-block: 16px; }
  .outlook-next { padding-left: 16px; }
  .accumulation-cycle { grid-template-columns: 1fr; gap: 16px; }
  h3 { font-size: 20px; }
}
</style>
