<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { useAccumulationPanel } from '../../composables/useAccumulationPanel'
import { accumulationActionCopy, isAccumulationStrategyChange } from '../../helpers/accumulation'

const route = useRoute()
const requested = computed(() => typeof route?.query.symbol === 'string' ? route.query.symbol : undefined)
const panel = useAccumulationPanel(requested.value)
const { detail, draft, uncertain, selected, busy, disabled, fresh, actions, error, notice } = panel
watch(requested, symbol => { if (symbol && symbol !== selected.value) void panel.selectSymbol(symbol) })
const registrations = computed(() => panel.rows.value.map(row => ({ label: row.symbol, value: row.symbol })))
const versions = computed(() => panel.strategies.value.map(version => ({ label: `${version.name} · v${version.version} · ${version.parameters.timeframe}`, value: version.id })))
const current = computed(() => versions.value.find(version => version.value === detail.value?.strategy_version_id)?.label ?? `Version ${detail.value?.strategy_version_id ?? 'unavailable'}`)
const action = computed(() => actions.value.includes('switch_strategy') ? 'switch_strategy' : actions.value.includes('retry_entry') ? 'retry_entry' : null)
const reviewHeading = ref<HTMLElement | null>(null)
const reviewButton = ref<{ $el: HTMLElement } | null>(null)
const currentLabel = ref<HTMLElement | null>(null)
async function restoreFocus() {
  await nextTick()
  const button = reviewButton.value?.$el
  if (button?.isConnected && !button.matches(':disabled')) button.focus()
  else currentLabel.value?.focus()
}
watch(() => draft.value?.operation_id, async id => {
  await nextTick()
  if (id) reviewHeading.value?.focus()
  else if (!busy.value) void restoreFocus()
})
watch(busy, (sending, previous) => { if (previous && !sending) void restoreFocus() })
function prepare() { if (action.value) panel.prepare(action.value) }
</script>

<template>
  <section class="strategy-assignment" aria-label="Existing accumulation strategy">
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-if="notice" role="status">{{ notice }}</p>
    <p v-if="!selected && !panel.loading.value && !panel.rows.value.length">No existing accumulation registrations.</p>
    <label for="strategy-registration">Registration</label>
    <n-select :value="selected" :options="registrations" :disabled="busy || !!uncertain || !!draft" :input-props="{ id: 'strategy-registration' }" @update:value="panel.selectSymbol" />
    <n-button v-if="panel.next.value" :disabled="busy" @click="panel.loadPage(true)">Load more registrations</n-button>
    <p v-if="detail" ref="currentLabel" tabindex="-1">Current strategy for {{ detail.symbol }}: {{ current }}</p>
    <n-button v-if="!fresh" :loading="panel.loading.value" :disabled="busy" @click="panel.loadPage()">Refresh registration status</n-button>
    <template v-if="uncertain">
      <p role="status">Unconfirmed request for {{ uncertain.symbol }}.</p>
      <n-button v-if="isAccumulationStrategyChange(uncertain)" :disabled="busy || !panel.available.value" :loading="busy" @click="panel.submit()">Retry same strategy request</n-button>
      <RouterLink v-else :to="{ name: 'controlCenter', query: { mode: 'utilities', symbol: uncertain.symbol }, hash: '#accumulation-controls' }">Resolve recorded request in Utilities</RouterLink>
    </template>
    <p v-else-if="panel.pendingRequest.value" role="status">Resolve the pending request for {{ panel.pendingRequest.value.symbol }} before changing a strategy.</p>
    <template v-if="detail && action">
      <label for="existing-accumulation-strategy">Strategy for this registration</label>
      <n-select filterable v-model:value="panel.targetVersion.value" :options="versions" :disabled="disabled" :input-props="{ id: 'existing-accumulation-strategy' }" placeholder="Select a saved version" />
      <p>Confirmed changes apply to this registration. The setup draft is saved separately.</p>
      <p v-if="panel.strategyError.value" role="alert">{{ panel.strategyError.value }}</p>
      <n-button v-if="panel.strategyError.value || panel.strategyCursor.value !== null" :disabled="busy || panel.strategyLoading.value" @click="panel.loadStrategies(panel.strategyCursor.value !== null)">Load strategies</n-button>
      <p v-if="action === 'retry_entry'">Applying this version also retries this registration’s entry check.</p>
      <n-button ref="reviewButton" :disabled="disabled || !panel.targetVersion.value || panel.targetVersion.value === detail.strategy_version_id" @click="prepare">Review strategy change</n-button>
    </template>
    <p v-else-if="detail && !uncertain">Strategy changes are unavailable in the current state.</p>
    <div v-if="draft && detail" role="region" aria-label="Review strategy change">
      <h3 ref="reviewHeading" tabindex="-1">Review strategy change · {{ draft.symbol }}</h3>
      <p>{{ accumulationActionCopy(draft.action, draft.symbol) }}</p>
      <p>Selected strategy: {{ versions.find(version => version.value === draft!.target_version_id)?.label }}</p>
      <p v-if="panel.confirmBlockedReason.value" role="status">{{ panel.confirmBlockedReason.value }}</p>
      <n-space>
        <n-button type="primary" :disabled="!!panel.confirmBlockedReason.value" :loading="busy" @click="panel.submit()">Confirm strategy change</n-button>
        <n-button :disabled="busy" @click="panel.draft.value = null">Cancel</n-button>
      </n-space>
    </div>
  </section>
</template>

<style scoped>
.strategy-assignment { display: grid; gap: 12px; max-width: 640px; padding-block: 16px; }
p { margin: 0; color: var(--mw-color-text-secondary); }
label { font-size: 14px; color: var(--mw-color-text-secondary); }
h3 { font-size: 20px; }
h3:focus-visible { outline: var(--mw-focus-ring); outline-offset: var(--mw-focus-offset); }
@media (max-width: 767px) { .strategy-assignment :deep(.n-button), .strategy-assignment :deep(.n-base-selection) { min-height: 44px; } }
</style>
