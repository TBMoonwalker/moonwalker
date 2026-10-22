<script setup lang="ts">
import { computed } from 'vue'
import type { AccumulationDetail, AccumulationStrategy } from '../types/accumulation'
import { accumulationOutlook } from '../helpers/accumulationPresentation'

const props = defineProps<{ detail: AccumulationDetail; fresh: boolean; strategy?: AccumulationStrategy }>()
const outlook = computed(() => accumulationOutlook(props.detail, props.fresh))
// A polling refresh must not unmount an expanded explanation or lose its focus.
const stepHelp = computed(() => accumulationOutlook(props.detail, true).help)
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
    <p v-if="strategy" class="strategy-summary">{{ strategy.name }} · v{{ strategy.version }} · {{ strategy.parameters.timeframe }}</p>
    <details v-if="stepHelp === 'entry'" class="step-help">
      <summary>Entry check details</summary>
      <p>The first check runs automatically. An incomplete check leaves buying paused until an explicit retry.</p>
      <p>Retry checks exchange access, inventory ownership, the saved strategy and market history. Passing enables strategy-driven buying; the check itself submits no order.</p>
    </details>
    <details v-else-if="stepHelp === 'buy'" class="step-help">
      <summary>Buying rules</summary>
      <p>{{ strategy ? `The strategy evaluates completed ${strategy.parameters.timeframe} candles.` : 'The strategy evaluates completed candles.' }} Qualifying dips can trigger buys within available budget. Deeper dips can use more budget.</p>
    </details>
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
.strategy-summary { padding-bottom: 16px; font-size: 14px; color: var(--mw-color-text-primary); }
.step-help { border-top: 1px solid var(--mw-color-border); }
.step-help summary { cursor: pointer; min-height: 44px; padding: 12px 0; font-size: 14px; color: var(--mw-color-text-secondary); }
.step-help summary:focus-visible { outline: var(--mw-focus-ring); outline-offset: var(--mw-focus-offset); }
.step-help p { padding-bottom: 16px; font-size: 14px; }
@media (max-width: 767px) {
  .outlook-now { grid-template-columns: 1fr; gap: 24px; padding-block: 16px; }
  .outlook-next { padding-left: 16px; }
  h3 { font-size: 20px; }
}
</style>
