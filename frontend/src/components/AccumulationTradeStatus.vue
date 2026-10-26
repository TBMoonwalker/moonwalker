<script setup lang="ts">
import AccumulationPanel from './AccumulationPanel.vue'
import AccumulationOrderTimeline from './AccumulationOrderTimeline.vue'
import { useAccumulationPanel } from '../composables/useAccumulationPanel'
const props = defineProps<{ symbol: string; context?: ReturnType<typeof useAccumulationPanel>; hideOutlook?: boolean; intent?: { action: string; id: number } | null }>()
const panel = props.context ?? useAccumulationPanel(props.symbol)
</script>

<template>
  <section class="accumulation-trade-status" :aria-label="`${symbol} accumulation`">
    <AccumulationPanel v-if="hideOutlook" :symbol="symbol" :context="panel" hide-outlook :intent="intent" />
    <AccumulationOrderTimeline v-else :detail="panel.detail.value">
      <template #base-order><AccumulationPanel :symbol="symbol" :context="panel" :intent="intent" /></template>
    </AccumulationOrderTimeline>
  </section>
</template>

<style scoped>
.accumulation-trade-status { min-width: 0; }
</style>
