<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import { useAccumulationPanel } from '../composables/useAccumulationPanel'
import { accumulationPendingStatus } from '../helpers/accumulationPresentation'

const panel = useAccumulationPanel()
const entries = computed(() => panel.rows.value.filter(row => !row.holding && row.state !== 'stopped'))
</script>

<template>
  <div v-if="panel.visible.value && (entries.length || panel.error.value || panel.uncertain.value)" class="pending-accumulation" aria-label="Pending accumulation entries">
    <p v-if="panel.error.value" role="alert">{{ panel.error.value }}</p>
    <div v-for="entry in entries" :key="entry.activation_id" class="pending-entry" role="status">
      <strong>{{ entry.symbol }}</strong>
      <span>{{ accumulationPendingStatus(entry, panel.fresh.value) }}</span>
      <RouterLink v-if="entry.state !== 'enabled'" :to="{ name: 'controlCenter', query: { mode: 'utilities', symbol: entry.symbol }, hash: '#accumulation-controls' }">Resolve entry issue</RouterLink>
    </div>
    <RouterLink v-if="panel.uncertain.value" :to="{ name: 'controlCenter', query: { mode: 'utilities', symbol: panel.uncertain.value.symbol }, hash: '#accumulation-controls' }">Resolve unconfirmed request for {{ panel.uncertain.value.symbol }}</RouterLink>
    <n-button v-if="panel.next.value" :disabled="panel.loading.value" @click="panel.loadPage(true)">Load more pending entries</n-button>
  </div>
</template>

<style scoped>
.pending-accumulation { display: grid; gap: 12px; padding: 16px; border-bottom: 1px solid var(--mw-color-border); }
.pending-entry { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; font-size: 14px; }
.pending-entry > span { color: var(--mw-color-text-secondary); }
p { margin: 0; }
</style>
