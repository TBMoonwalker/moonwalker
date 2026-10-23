<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import AccumulationOutlook from './AccumulationOutlook.vue'
import { useAccumulationPanel } from '../composables/useAccumulationPanel'
import { accumulationActionCopy, accumulationActionLabels, accumulationReason, isAccumulationStrategyChange } from '../helpers/accumulation'

const props = defineProps<{ symbol?: string; context?: ReturnType<typeof useAccumulationPanel>; hideOutlook?: boolean; intent?: { action: string; id: number } | null }>()
const route = useRoute()
const requestedSymbol = computed(() => props.symbol ?? (typeof route?.query.symbol === 'string' ? route.query.symbol : undefined))
const panel = props.context ?? useAccumulationPanel(requestedSymbol.value)
watch(requestedSymbol, symbol => {
  if (symbol && symbol !== panel.selected.value) void panel.selectSymbol(symbol)
})
const { visible, available, rows, selected, detail, loading, fresh, busy, error, notice, draft, uncertain, csv, actions, disabled } = panel

const fieldId = (name: string) => `${selected.value ?? 'accumulation'}-${name}`
const quote = computed(() => detail.value?.symbol.split('/')[1] ?? '')
const base = computed(() => detail.value?.symbol.split('/')[0] ?? '')
const pinnedStrategy = computed(() => panel.strategies.value.find(version => version.id === detail.value?.strategy_version_id))
const routineActions = computed(() => actions.value.filter(action => ['pause', 'resume', 'close', 'retry_close', 'reactivate', 'abandon_entry', 'retry_entry'].includes(action)))
const secondaryActions = computed(() => actions.value.filter(action => !routineActions.value.includes(action) && action !== 'sell_partial' && action !== 'switch_strategy'))
const repairOptions = computed(() => (detail.value?.quarantined_orders ?? []).filter(order => order.has_lookup_identity).map((order, index) => ({ value: order.placement_operation_id, label: `${order.side === 'buy' ? 'Buy' : 'Manual sale'} · restored order ${index + 1}` })))
const reviewedRepair = computed(() => repairOptions.value.find(option => option.value === draft.value?.placement_operation_id))
const retirementOptions = computed(() => (detail.value?.quarantined_commands ?? []).map((operation, index) => ({
  value: operation.operation_id, label: `${accumulationReason(operation.action)} · interrupted request ${index + 1}`,
})))
const reviewedRetirement = computed(() => retirementOptions.value.find(option => option.value === draft.value?.previous_operation_id))

const handledIntent = ref<number | null>(null)
const partialSaleOpen = ref(false)
const reviewHeading = ref<HTMLElement | null>(null)
const partialQuantity = ref<{ focus: () => void } | null>(null)
const initiatingButton = ref<HTMLElement | null>(null)
const controls = ref<HTMLElement | null>(null)
function prepare(action: Parameters<typeof panel.prepare>[0], event?: Event) {
  initiatingButton.value = event?.currentTarget instanceof HTMLElement ? event.currentTarget : null
  panel.prepare(action)
}
async function openPartialSale() {
  partialSaleOpen.value = true
  await nextTick()
  partialQuantity.value?.focus()
}
watch(() => draft.value?.operation_id, async id => {
  await nextTick()
  if (id) reviewHeading.value?.focus()
  else if (initiatingButton.value?.isConnected) initiatingButton.value.focus()
  else controls.value?.focus()
})
watch([() => props.intent?.id, fresh], async () => {
  if (!props.intent || handledIntent.value === props.intent.id || !fresh.value || draft.value || uncertain.value) return
  handledIntent.value = props.intent.id
  const action = props.intent.action
  if (action === 'sell_partial' && actions.value.includes('sell_partial')) await openPartialSale()
  else if (action === 'adjust_inventory') {
    await nextTick()
    const correction = controls.value?.querySelector<HTMLDetailsElement>('.inventory-correction')
    if (correction) { correction.open = true; correction.querySelector<HTMLElement>('summary')?.focus() }
    else notice.value = 'Inventory corrections require a paused trade with settled orders and verified ownership.'
  } else if (routineActions.value.includes(action as typeof routineActions.value[number])) panel.prepare(action as typeof routineActions.value[number])
  else notice.value = 'This action is unavailable in the current trade state. Review the status and available controls.'
}, { immediate: true })
</script>

<template>
  <section v-if="visible" ref="controls" tabindex="-1" class="accumulation-panel" :aria-label="`${detail?.symbol ?? symbol ?? 'Accumulation'} trade information`">
    <n-button v-if="!fresh" :loading="loading" :disabled="busy" @click="panel.loadPage()">Refresh status</n-button>
    <n-alert v-if="error" type="warning" role="alert">{{ error }}</n-alert>
    <n-alert v-if="notice" type="info" role="status">{{ notice }}</n-alert>
    <n-alert v-if="panel.pendingRequest.value && panel.pendingRequest.value.symbol !== selected" type="warning" role="alert">
      Resolve the pending request for {{ panel.pendingRequest.value.symbol }} before starting another action.
      <RouterLink :to="{ name: 'trades', query: { symbol: panel.pendingRequest.value.symbol } }">Open pending request</RouterLink>
    </n-alert>
    <n-alert v-if="uncertain" type="warning" role="alert">
      {{ uncertain.action === 'repair_order' ? 'Order evidence required' : uncertain.action === 'rebind_account' ? 'Account evidence required' : 'Unconfirmed request' }}: {{ accumulationActionLabels[uncertain.action] }} — {{ uncertain.symbol }}.
      <RouterLink v-if="isAccumulationStrategyChange(uncertain)" :to="{ name: 'controlCenter', query: { mode: 'setup', target: 'dca', symbol: uncertain.symbol }, hash: '#accumulation-strategy-assignments' }">Review strategy request in Configuration</RouterLink>
      <n-button v-else :loading="busy" :disabled="busy || !available" @click="panel.submit()">Retry same request</n-button>
    </n-alert>
    <p v-if="available && rows.length === 0">No accumulation registrations. Add a fixed symbol with ASAP or import an existing holding with CSV.</p>
    <template v-if="detail">
      <AccumulationOutlook v-if="!hideOutlook" :detail="detail" :fresh="fresh" compact />
      <p class="assigned-strategy">{{ pinnedStrategy ? `${pinnedStrategy.name} · v${pinnedStrategy.version} · ${pinnedStrategy.parameters.timeframe}` : detail.strategy_slug ?? 'Strategy unavailable' }}</p>
      <div v-if="!hideOutlook" class="accumulation-actions">
        <n-button v-for="action in routineActions" :key="action" :disabled="disabled" @click="prepare(action, $event)">{{ action === 'close' && detail.holding ? 'Sell and close' : accumulationActionLabels[action] }}</n-button>
        <n-button v-if="actions.includes('sell_partial')" :disabled="disabled" :aria-expanded="partialSaleOpen" @click="openPartialSale">Sell part</n-button>
      </div>
      <div v-if="partialSaleOpen && actions.includes('sell_partial')" class="accumulation-input">
        <label :for="`partial-sale-${detail.symbol}`">Partial sale quantity · {{ base }}</label>
        <n-input ref="partialQuantity" v-model:value="panel.quantity.value" :disabled="disabled" :input-props="{ id: `partial-sale-${detail.symbol}`, inputmode: 'decimal' }" />
        <n-button :disabled="disabled || !panel.quantity.value" @click="prepare('sell_partial', $event)">Review partial sale</n-button>
      </div>
      <n-alert v-if="detail.holding_integrity === 'invalid'" type="error">Ownership needs repair. Restore the recorded inventory link before trading.</n-alert>
      <n-alert v-if="detail.account_matches === false" type="warning">The configured credentials differ from this holding's recorded account binding. Wallet balance alone is not proof. Credential revalidation requires matching native order history, complete fees, settled original-account work and enough free inventory. Buying will stay paused.</n-alert>
      <n-alert v-if="detail.quarantined_orders?.length" type="warning">Restored orders remain quarantined. Reconcile them before changing this holding. A missing or inconclusive exchange report cannot release the recorded commitment.</n-alert>
      <n-alert v-if="detail.quarantined_commands?.length" type="warning">Interrupted commands remain quarantined. Retire the old intents before choosing new actions. Commands with attached orders require order reconciliation first.</n-alert>
      <n-alert v-if="detail.state === 'closing'" type="warning">
        Closing blocks new buys. Any remaining quantity stays recorded, including dust below the exchange minimum. Retry a remaining sale only after it becomes sellable; unsettled orders must reconcile first.
      </n-alert>
      <n-alert v-if="draft" type="warning" role="region" aria-label="Review trade action">
        <h4 ref="reviewHeading" tabindex="-1">Review {{ accumulationActionLabels[draft.action].toLowerCase() }} · {{ draft.symbol }}</h4>
        <p>{{ accumulationActionCopy(draft.action, draft.symbol) }}</p>
        <p v-if="draft.quantity">Quantity: <strong>{{ draft.quantity }}</strong> {{ base }}</p>
        <template v-if="draft.action === 'adjust_inventory'">
          <p>Direction: <strong>{{ draft.direction }}</strong>. Acquisition cost: <strong>{{ draft.acquisition_cost ?? 'Unknown / proportional existing basis for a removal' }}</strong> {{ quote }}.</p>
          <p>Reason: {{ draft.note }}</p>
        </template>
        <p v-if="draft.action === 'declare_ownership'">Ownership declared for <strong>{{ draft.confirmation }}</strong>: {{ draft.note }}</p>
        <p v-if="reviewedRepair">Selected order: {{ reviewedRepair.label }}</p>
        <p v-if="draft.action === 'retire_command' && reviewedRetirement">Selected command: {{ reviewedRetirement.label }}</p>
        <pre v-if="draft.csv_content" class="accumulation-csv-review">{{ draft.csv_content }}</pre>
        <p v-if="draft.expected_revision !== detail.revision">The holding changed. Cancel this review and choose the action again.</p>
        <div class="accumulation-actions">
          <p v-if="panel.confirmBlockedReason.value" role="status">{{ panel.confirmBlockedReason.value }}</p>
          <n-button type="primary" :loading="busy" :disabled="!!panel.confirmBlockedReason.value" @click="panel.submit()">Confirm {{ accumulationActionLabels[draft.action].toLowerCase() }}</n-button>
          <n-button :disabled="busy" @click="draft = null">Cancel</n-button>
        </div>
      </n-alert>
    </template>
    <template v-if="detail">
      <details v-if="detail.holding" class="holding-evidence">
        <summary>Current holding</summary>
        <dl class="accumulation-values">
        <div><dt>Managed quantity · {{ base }}</dt><dd>{{ detail.holding.net_quantity ?? 'Unknown' }}</dd></div>
        <div><dt>Remaining cost · {{ quote }}</dt><dd>{{ detail.holding.remaining_cost ?? 'Unknown' }}</dd></div>
        <div><dt>Contributed · {{ quote }}</dt><dd>{{ detail.holding.contributed_quote ?? 'Unknown' }}</dd></div>
        <div><dt>Disposal proceeds · {{ quote }}</dt><dd>{{ detail.holding.disposal_proceeds ?? 'Unknown' }}</dd></div>
        <div><dt>Cost basis</dt><dd>{{ detail.holding.basis_provenance ? accumulationReason(detail.holding.basis_provenance) : 'Unknown' }}</dd></div>
        <div><dt>Recorded fees</dt><dd>{{ detail.holding.fees ? Object.entries(detail.holding.fees.totals).map(([currency, amount]) => `${amount} ${currency}`).join(' · ') || '0' : 'Unknown' }}</dd></div>
      </dl>
      </details>
      <p v-else-if="detail.inventory_restore_required">Recorded inventory is missing from its holding link. Restore it from audit evidence before trading.</p>
      <p v-else-if="detail.holding_integrity !== 'invalid' && detail.observations_initialized">No managed inventory.</p>
      <p v-if="detail.holding && (!detail.holding.fees || detail.holding.fees.pending_reports > 0 || !detail.holding.execution_history_complete)">
        Fee or execution history is incomplete. These amounts do not represent a fully verified net return.
      </p>
      <dl v-if="detail.entry?.declaration && !detail.observations_initialized" class="accumulation-values">
        <div><dt>Declared quantity · {{ base }}</dt><dd>{{ detail.entry.declaration.net_quantity }}</dd></div>
        <div><dt>Declared cost · {{ quote }}</dt><dd>{{ detail.entry.declaration.acquisition_cost }}</dd></div>
      </dl>
      <p v-if="!detail.observations_initialized && detail.entry?.source === 'csv'">CSV amounts declare net owned coins. Historical fees remain unknown. Correction does not enable buys.</p>
      <div v-if="actions.includes('correct_import')" class="accumulation-input">
        <label :for="fieldId('accumulation-csv')">Corrected CSV for {{ detail.symbol }}</label>
        <n-input v-model:value="csv" type="textarea" :disabled="disabled" :input-props="{ id: fieldId('accumulation-csv') }" placeholder="date;symbol;price;amount" :autosize="{ minRows: 3, maxRows: 8 }" />
      </div>
      <details v-if="actions.includes('declare_ownership')" class="accumulation-input">
        <summary>Explicit ownership declaration</summary>
        <p>Use only after verifying that the recorded coins belong to you in the newly configured account. Return history becomes unverified and buying stays paused.</p>
        <label :for="fieldId('accumulation-ownership-confirmation')">Type {{ detail.symbol }} exactly</label>
        <n-input v-model:value="panel.ownershipConfirmation.value" :disabled="disabled" :input-props="{ id: fieldId('accumulation-ownership-confirmation') }" />
        <label :for="fieldId('accumulation-ownership-note')">Ownership declaration reason</label>
        <n-input v-model:value="panel.ownershipNote.value" :disabled="disabled" :input-props="{ id: fieldId('accumulation-ownership-note'), maxlength: 500 }" />
      </details>
      <details v-if="actions.includes('adjust_inventory')" class="accumulation-input inventory-correction">
        <summary>Inventory correction</summary>
        <p>Use this for a deliberate correction to managed coins. Pause and settle all orders first. A correction cannot clear a holding or remove closing dust.</p>
        <label :for="fieldId('accumulation-adjustment-direction')">Correction direction</label>
        <n-select v-model:value="panel.adjustmentDirection.value" :options="[{ label: 'Add declared inventory', value: 'add' }, { label: 'Remove part of managed inventory', value: 'remove' }]" :disabled="disabled" :input-props="{ id: fieldId('accumulation-adjustment-direction') }" />
        <label :for="fieldId('accumulation-adjustment-quantity')">Correction quantity · {{ base }}</label>
        <n-input v-model:value="panel.adjustmentQuantity.value" :disabled="disabled" :input-props="{ id: fieldId('accumulation-adjustment-quantity'), inputmode: 'decimal' }" placeholder="Exact quantity to add or remove" />
        <template v-if="panel.adjustmentDirection.value === 'add'">
          <label :for="fieldId('accumulation-adjustment-cost')">Acquisition cost of added coins · {{ quote }}</label>
          <n-input v-model:value="panel.adjustmentCost.value" :disabled="disabled" :input-props="{ id: fieldId('accumulation-adjustment-cost'), inputmode: 'decimal' }" placeholder="Leave blank when unknown" />
          <p>Unknown cost makes remaining cost and contributed quote unknown. Historical fees remain unverified.</p>
        </template>
        <label :for="fieldId('accumulation-adjustment-note')">Correction reason</label>
        <n-input v-model:value="panel.adjustmentNote.value" :disabled="disabled" :input-props="{ id: fieldId('accumulation-adjustment-note'), maxlength: 500 }" placeholder="Why this inventory declaration needs correction" />
      </details>
      <div v-if="actions.includes('repair_order')" class="accumulation-input">
        <label :for="fieldId('accumulation-repair-order')">Quarantined order</label>
        <n-select v-model:value="panel.repairTarget.value" :options="repairOptions" :disabled="disabled" :input-props="{ id: fieldId('accumulation-repair-order') }" />
        <p>Reconciliation needs terminal exchange evidence with complete fees. Orders without a stored lookup identity require manual investigation.</p>
      </div>
      <div v-if="actions.includes('retire_command')" class="accumulation-input">
        <label :for="fieldId('accumulation-retirement')">Interrupted command</label>
        <n-select v-model:value="panel.retirementTarget.value" :options="retirementOptions" :disabled="disabled" :input-props="{ id: fieldId('accumulation-retirement') }" />
        <p>Retirement keeps the holding paused. Entry declarations stay recorded and a close remains in Closing.</p>
      </div>
      <div v-if="secondaryActions.length" class="accumulation-actions">
        <n-button v-for="action in secondaryActions" :key="action" :disabled="disabled" @click="prepare(action, $event)">{{ accumulationActionLabels[action] }}</n-button>
      </div>
    </template>

  </section>
</template>

<style scoped>
.accumulation-panel { display: grid; gap: 16px; min-width: 0; }
.assigned-strategy { margin-right: auto; font-size: 14px; color: var(--mw-color-text-secondary); }
h4 { margin: 0 0 8px; font-size: 16px; }
h4:focus-visible { outline: var(--mw-focus-ring); outline-offset: var(--mw-focus-offset); }
.accumulation-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; }
p { margin: 8px 0 0; color: var(--mw-color-text-secondary); }
.accumulation-input { display: grid; gap: 8px; }
.accumulation-input { max-width: 720px; }
label, dt { font-size: 14px; color: var(--mw-color-text-secondary); }
.accumulation-values { display: grid; grid-template-columns: 1fr; gap: 16px; margin: 0; }
dd { margin: 4px 0 0; font-family: var(--mw-font-mono); overflow-wrap: anywhere; }
.accumulation-csv-review { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 240px; overflow-y: auto; }
summary { cursor: pointer; padding: 12px 0; margin: 0; min-height: 44px; font-size: 14px; color: var(--mw-color-text-primary); font-weight: 500; }
.accumulation-values dd { font-size: 14px; color: var(--mw-color-text-primary); }
summary:focus-visible { outline: 2px solid var(--mw-color-primary); outline-offset: 3px; }
@media (max-width: 767px) {

  .accumulation-panel :deep(.n-button), .accumulation-panel :deep(.n-base-selection), .accumulation-panel :deep(.n-input) { min-height: 44px; }
  .accumulation-actions { align-items: stretch; }
}
</style>
