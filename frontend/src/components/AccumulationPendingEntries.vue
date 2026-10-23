<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { useAccumulationPanel } from '../composables/useAccumulationPanel'
import { accumulationPendingStatus } from '../helpers/accumulationPresentation'
import AccumulationTradeStatus from './AccumulationTradeStatus.vue'
const props = defineProps<{ context: ReturnType<typeof useAccumulationPanel>; openSymbols: string[] }>()
const panel = props.context
const route = useRoute()
const selected = ref<string | null>(null)
watch(() => route?.query.symbol, symbol => { if (typeof symbol === 'string') selected.value = symbol }, { immediate: true })
const entries = computed(() => panel.rows.value.filter(row => !props.openSymbols.includes(row.symbol)))
const requestedOutsidePage = computed(() => selected.value && !props.openSymbols.includes(selected.value) && !entries.value.some(row => row.symbol === selected.value))
function toggle(symbol: string, event: Event) { if ((event.target as HTMLDetailsElement).open) selected.value = symbol; else if (selected.value === symbol) selected.value = null }
</script>

<template>
  <section v-if="panel.visible.value && (entries.length || requestedOutsidePage || panel.error.value || panel.pendingRequest.value)" class="pending-accumulation" aria-label="Accumulation registrations">
    <p v-if="panel.error.value" role="alert">{{ panel.error.value }}</p>
    <details v-for="entry in entries" :key="entry.activation_id" class="pending-entry" :open="selected === entry.symbol" @toggle="toggle(entry.symbol, $event)">
      <summary><strong>{{ entry.symbol }}</strong> <span>{{ accumulationPendingStatus(entry, panel.fresh.value) }}</span></summary>
      <AccumulationTradeStatus v-if="selected === entry.symbol" :key="entry.symbol" :symbol="entry.symbol" />
    </details>
    <AccumulationTradeStatus v-if="requestedOutsidePage" :key="selected!" :symbol="selected!" />
    <RouterLink v-if="panel.pendingRequest.value" :to="{ name: 'trades', query: { symbol: panel.pendingRequest.value.symbol } }">Resolve unconfirmed request for {{ panel.pendingRequest.value.symbol }}</RouterLink>
    <n-button v-if="panel.next.value" :disabled="panel.loading.value" @click="panel.loadPage(true)">Load more registrations</n-button>
  </section>
</template>

<style scoped>
.pending-accumulation { display: grid; gap: 12px; padding: 16px; border-bottom: 1px solid var(--mw-color-border); }
summary { cursor: pointer; min-height: 44px; align-content: center; font-size: 14px; }
summary span { margin-left: 12px; color: var(--mw-color-text-secondary); }
summary:focus-visible { outline: var(--mw-focus-ring); outline-offset: var(--mw-focus-offset); }
p { margin: 0; }
</style>
