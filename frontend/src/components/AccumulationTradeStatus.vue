<script setup lang="ts">
import AccumulationPanel from './AccumulationPanel.vue'
import type { useAccumulationPanel } from '../composables/useAccumulationPanel'
defineProps<{ symbol: string; context?: ReturnType<typeof useAccumulationPanel>; hideOutlook?: boolean; intent?: { action: string; id: number } | null }>()
</script>

<template>
  <section class="accumulation-trade-status" :aria-label="`${symbol} accumulation`">
    <AccumulationPanel :symbol="symbol" :context="context" :hide-outlook="hideOutlook" :intent="intent" />
  </section>
</template>

<style scoped>
.accumulation-trade-status { min-width: 0; }
</style>
