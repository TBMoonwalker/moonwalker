<script setup lang="ts">
import { computed, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import AccumulationReplay from './AccumulationReplay.vue'
import AccumulationOutlook from './AccumulationOutlook.vue'
import { accumulationOutlook } from '../helpers/accumulationPresentation'
import { useAccumulationPanel } from '../composables/useAccumulationPanel'
import { accumulationActionCopy, accumulationActionLabels, accumulationReason, isAccumulationStrategyChange } from '../helpers/accumulation'

const route = useRoute()
const requestedSymbol = computed(() => typeof route?.query.symbol === 'string' ? route.query.symbol : undefined)
const panel = useAccumulationPanel(requestedSymbol.value)
watch(requestedSymbol, symbol => {
  if (symbol && symbol !== panel.selected.value) void panel.selectSymbol(symbol)
})
const { visible, available, rows, portfolio, next, selected, detail, loading, fresh, busy, error, notice, draft, uncertain, csv, actions, disabled } = panel
const options = computed(() => rows.value.map(row => ({ label: `${row.symbol} · ${accumulationReason(row.state)}`, value: row.symbol })))
const quote = computed(() => detail.value?.symbol.split('/')[1] ?? '')
const base = computed(() => detail.value?.symbol.split('/')[0] ?? '')
const pinnedStrategy = computed(() => panel.strategies.value.find(version => version.id === detail.value?.strategy_version_id))
const primaryAction = computed(() => {
  // Keep the button mounted so keyboard focus survives pushed status updates.
  const action = detail.value ? accumulationOutlook(detail.value, true).action : undefined
  return action && actions.value.includes(action) ? action : undefined
})
const secondaryActions = computed(() => actions.value.filter(action => action !== primaryAction.value && action !== 'sell_partial' && action !== 'switch_strategy'))
const repairOptions = computed(() => (detail.value?.quarantined_orders ?? []).filter(order => order.has_lookup_identity).map((order, index) => ({ value: order.placement_operation_id, label: `${order.side === 'buy' ? 'Buy' : 'Manual sale'} · restored order ${index + 1}` })))
const reviewedRepair = computed(() => repairOptions.value.find(option => option.value === draft.value?.placement_operation_id))
const retirementOptions = computed(() => (detail.value?.quarantined_commands ?? []).map((operation, index) => ({
  value: operation.operation_id, label: `${accumulationReason(operation.action)} · interrupted request ${index + 1}`,
})))
const reviewedRetirement = computed(() => retirementOptions.value.find(option => option.value === draft.value?.previous_operation_id))
</script>

<template>
  <section v-if="visible" id="accumulation-controls" class="dashboard-panel accumulation-panel" aria-labelledby="accumulation-heading">
    <header class="accumulation-heading">
      <div>
        <h2 id="accumulation-heading">Accumulation</h2>
      </div>
      <span class="accumulation-live" role="status">{{ !panel.streamAvailable.value ? 'Snapshot' : panel.streamStatus.value === 'OPEN' ? 'Live' : 'Reconnecting' }}</span>
      <n-button :loading="loading" :disabled="busy" @click="panel.loadPage()">Refresh status</n-button>
    </header>
    <n-alert v-if="error" type="warning" role="alert">{{ error }}</n-alert>
    <n-alert v-if="notice" type="info" role="status">{{ notice }}</n-alert>
    <n-alert v-if="panel.pendingRequest.value && panel.pendingRequest.value.symbol !== selected" type="warning" role="alert">
      Resolve the pending request for {{ panel.pendingRequest.value.symbol }} before starting another action.
      <RouterLink :to="{ name: 'controlCenter', query: { mode: 'utilities', symbol: panel.pendingRequest.value.symbol }, hash: '#accumulation-controls' }">Open pending request</RouterLink>
    </n-alert>
    <n-alert v-if="uncertain" type="warning" role="alert">
      {{ uncertain.action === 'repair_order' ? 'Order evidence required' : uncertain.action === 'rebind_account' ? 'Account evidence required' : 'Unconfirmed request' }}: {{ accumulationActionLabels[uncertain.action] }} — {{ uncertain.symbol }}.
      <RouterLink v-if="isAccumulationStrategyChange(uncertain)" :to="{ name: 'controlCenter', query: { mode: 'setup', target: 'dca', symbol: uncertain.symbol }, hash: '#accumulation-strategy-assignments' }">Review strategy request in Configuration</RouterLink>
      <n-button v-else :loading="busy" :disabled="busy || !available" @click="panel.submit()">Retry same request</n-button>
    </n-alert>
    <p v-if="available && rows.length === 0">No accumulation registrations. Add a fixed symbol with ASAP or import an existing holding with CSV.</p>
    <div v-if="rows.length > 1" class="accumulation-picker">
      <label for="accumulation-symbol">Managed symbol</label>
      <n-select filterable :value="selected" :options="options" :input-props="{ id: 'accumulation-symbol' }" :disabled="busy || !!uncertain" @update:value="panel.selectSymbol" />
      <n-button v-if="next" :disabled="busy" @click="panel.loadPage(true)">Load more symbols</n-button>
    </div>

    <template v-if="detail">
      <AccumulationOutlook :detail="detail" :fresh="fresh">
        <n-button v-if="primaryAction" type="primary" :disabled="disabled" @click="panel.prepare(primaryAction)">{{ accumulationActionLabels[primaryAction] }}</n-button>
      </AccumulationOutlook>
      <n-alert v-if="detail.holding_integrity === 'invalid'" type="error">Ownership needs repair. Restore the recorded inventory link before trading.</n-alert>
      <n-alert v-if="detail.account_matches === false" type="warning">The configured credentials differ from this holding's recorded account binding. Wallet balance alone is not proof. Credential revalidation requires matching native order history, complete fees, settled original-account work and enough free inventory. Buying will stay paused.</n-alert>
      <n-alert v-if="detail.quarantined_orders?.length" type="warning">Restored orders remain quarantined. Reconcile them before changing this holding. A missing or inconclusive exchange report cannot release the recorded commitment.</n-alert>
      <n-alert v-if="detail.quarantined_commands?.length" type="warning">Interrupted commands remain quarantined. Retire the old intents before choosing new actions. Commands with attached orders require order reconciliation first.</n-alert>
      <n-alert v-if="detail.state === 'closing'" type="warning">
        Closing blocks new buys. Any remaining quantity stays recorded, including dust below the exchange minimum. Retry a remaining sale only after it becomes sellable; unsettled orders must reconcile first.
      </n-alert>
      <n-alert v-if="draft" type="warning" role="alert" title="Review action">
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
    <details class="accumulation-management">
      <summary>Manage accumulation</summary>
      <div class="accumulation-management-content">
    <template v-if="detail">
      <dl v-if="detail.holding" class="accumulation-values">
        <div><dt>Managed quantity · {{ base }}</dt><dd>{{ detail.holding.net_quantity ?? 'Unknown' }}</dd></div>
        <div><dt>Remaining cost · {{ quote }}</dt><dd>{{ detail.holding.remaining_cost ?? 'Unknown' }}</dd></div>
        <div><dt>Contributed · {{ quote }}</dt><dd>{{ detail.holding.contributed_quote ?? 'Unknown' }}</dd></div>
        <div><dt>Disposal proceeds · {{ quote }}</dt><dd>{{ detail.holding.disposal_proceeds ?? 'Unknown' }}</dd></div>
      </dl>
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
        <label for="accumulation-csv">Corrected CSV for {{ detail.symbol }}</label>
        <n-input v-model:value="csv" type="textarea" :disabled="disabled" :input-props="{ id: 'accumulation-csv' }" placeholder="date;symbol;price;amount" :autosize="{ minRows: 3, maxRows: 8 }" />
      </div>
      <details v-if="actions.includes('declare_ownership')" class="accumulation-input">
        <summary>Explicit ownership declaration</summary>
        <p>Use only after verifying that the recorded coins belong to you in the newly configured account. Return history becomes unverified and buying stays paused.</p>
        <label for="accumulation-ownership-confirmation">Type {{ detail.symbol }} exactly</label>
        <n-input v-model:value="panel.ownershipConfirmation.value" :disabled="disabled" :input-props="{ id: 'accumulation-ownership-confirmation' }" />
        <label for="accumulation-ownership-note">Ownership declaration reason</label>
        <n-input v-model:value="panel.ownershipNote.value" :disabled="disabled" :input-props="{ id: 'accumulation-ownership-note', maxlength: 500 }" />
      </details>
      <details v-if="actions.includes('adjust_inventory')" class="accumulation-input">
        <summary>Inventory correction</summary>
        <p>Use this for a deliberate correction to managed coins. Pause and settle all orders first. A correction cannot clear a holding or remove closing dust.</p>
        <label for="accumulation-adjustment-direction">Correction direction</label>
        <n-select v-model:value="panel.adjustmentDirection.value" :options="[{ label: 'Add declared inventory', value: 'add' }, { label: 'Remove part of managed inventory', value: 'remove' }]" :disabled="disabled" :input-props="{ id: 'accumulation-adjustment-direction' }" />
        <label for="accumulation-adjustment-quantity">Correction quantity · {{ base }}</label>
        <n-input v-model:value="panel.adjustmentQuantity.value" :disabled="disabled" :input-props="{ id: 'accumulation-adjustment-quantity', inputmode: 'decimal' }" placeholder="Exact quantity to add or remove" />
        <template v-if="panel.adjustmentDirection.value === 'add'">
          <label for="accumulation-adjustment-cost">Acquisition cost of added coins · {{ quote }}</label>
          <n-input v-model:value="panel.adjustmentCost.value" :disabled="disabled" :input-props="{ id: 'accumulation-adjustment-cost', inputmode: 'decimal' }" placeholder="Leave blank when unknown" />
          <p>Unknown cost makes remaining cost and contributed quote unknown. Historical fees remain unverified.</p>
        </template>
        <label for="accumulation-adjustment-note">Correction reason</label>
        <n-input v-model:value="panel.adjustmentNote.value" :disabled="disabled" :input-props="{ id: 'accumulation-adjustment-note', maxlength: 500 }" placeholder="Why this inventory declaration needs correction" />
      </details>
      <div v-if="actions.includes('repair_order')" class="accumulation-input">
        <label for="accumulation-repair-order">Quarantined order</label>
        <n-select v-model:value="panel.repairTarget.value" :options="repairOptions" :disabled="disabled" :input-props="{ id: 'accumulation-repair-order' }" />
        <p>Reconciliation needs terminal exchange evidence with complete fees. Orders without a stored lookup identity require manual investigation.</p>
      </div>
      <div v-if="actions.includes('retire_command')" class="accumulation-input">
        <label for="accumulation-retirement">Interrupted command</label>
        <n-select v-model:value="panel.retirementTarget.value" :options="retirementOptions" :disabled="disabled" :input-props="{ id: 'accumulation-retirement' }" />
        <p>Retirement keeps the holding paused. Entry declarations stay recorded and a close remains in Closing.</p>
      </div>
      <div class="accumulation-actions">
        <n-button v-for="action in secondaryActions" :key="action" :disabled="disabled" @click="panel.prepare(action)">{{ accumulationActionLabels[action] }}</n-button>
      </div>
      <details v-if="detail.operations.length" class="accumulation-history">
        <summary>Recent requests</summary>
        <p>These are recorded outcomes. Current holding state is shown above.</p>
        <ul><li v-for="operation in detail.operations" :key="operation.operation_id">
          {{ accumulationReason(operation.action) }} · {{ operation.status }} · {{ operation.result_state }}
          <template v-if="operation.adjustment">
            <p>{{ operation.adjustment.direction }} {{ operation.adjustment.quantity }} {{ base }} · {{ operation.adjustment.note }}</p>
            <p>Managed quantity: {{ operation.adjustment.before_quantity }} → {{ operation.adjustment.after_quantity }} {{ base }}. Remaining cost: {{ operation.adjustment.before_cost ?? 'Unknown' }} → {{ operation.adjustment.after_cost ?? 'Unknown' }} {{ quote }}.</p>
          </template>
        </li></ul>
        <p v-if="detail.older_operations_available">Showing the 20 most recent requests.</p>
      </details>
      <details v-if="detail.orders?.length" class="accumulation-history">
        <summary>Recent executed orders</summary>
        <p>One cumulative record per order. Later fills and fee corrections update that record. These amounts remain available after a full close and can include previous holdings of this symbol.</p>
        <ul class="accumulation-order-list">
          <li v-for="order in detail.orders" :key="order.checkpoint_id">
            <strong>{{ order.side === 'buy' ? 'Buy' : 'Manual sale' }}</strong> · {{ order.terminal ? 'Terminal order' : 'Order still open' }}
            <dl class="accumulation-values">
              <div><dt>Filled · {{ base }}</dt><dd>{{ order.filled_quantity ?? 'Unknown' }}</dd></div>
              <div><dt>Gross quote amount · {{ quote }}</dt><dd>{{ order.quote_cost ?? 'Unknown' }}</dd></div>
              <div><dt>Fees</dt><dd v-if="order.fees === null">Unknown</dd><dd v-for="(amount, currency) in order.fees" :key="currency">{{ amount }} {{ currency }}</dd></div>
              <div><dt>Remaining quantity at update · {{ base }}</dt><dd>{{ order.inventory_at_update?.net_quantity ?? 'Unknown' }}</dd></div>
              <div><dt>Remaining cost at update · {{ quote }}</dt><dd>{{ order.inventory_at_update?.remaining_cost ?? 'Unknown' }}</dd></div>
            </dl>
            <p v-if="!order.fees_complete || !order.inventory_at_update || order.inventory_at_update.pending_fee_reports || order.inventory_at_update.basis_provenance !== 'exchange_fills'">Basis or fee history is incomplete. This is not a verified net return.</p>
            <p>Last evidence update: {{ order.updated_at }}</p>
          </li>
        </ul>
        <p v-if="detail.older_orders_available">Showing the 20 most recent filled orders. Earlier records remain stored.</p>
      </details>
    </template>
    <details v-if="detail" class="accumulation-history">
      <summary>Strategy and status details</summary>
      <p v-if="pinnedStrategy">{{ pinnedStrategy.name }} · v{{ pinnedStrategy.version }} · {{ pinnedStrategy.parameters.timeframe }}</p>
      <div class="accumulation-state">
        <n-tag :type="detail.state === 'closing' || detail.state === 'blocked' ? 'warning' : 'default'">{{ accumulationReason(detail.state) }}</n-tag>
        <span>{{ detail.strategy_slug ?? 'Strategy unavailable' }}<template v-if="detail.strategy_version !== null"> · version {{ detail.strategy_version }}</template></span>
        <span v-if="!fresh">Status needs refresh</span>
      </div>
      <p v-if="detail.reason || detail.runtime_wait_reason">{{ accumulationReason(detail.reason || detail.runtime_wait_reason) }}</p>
      <p v-if="detail.reason && detail.runtime_wait_reason">Runtime: {{ accumulationReason(detail.runtime_wait_reason) }}</p>
    </details>
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

    <AccumulationReplay v-if="available" :strategies="panel.strategies.value" />
      </div>
    </details>
  </section>
</template>

<style scoped>
.accumulation-panel { padding: 24px; display: grid; gap: 16px; min-width: 0; }
.accumulation-heading, .accumulation-state, .accumulation-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; }
.accumulation-heading { justify-content: space-between; align-items: flex-start; }
h2 { margin: 0; font: 600 20px var(--mw-font-display); color: var(--mw-color-text-primary); }
p { margin: 8px 0 0; color: var(--mw-color-text-secondary); }
.accumulation-management-content { display: grid; gap: 16px; padding-top: 16px; }
.accumulation-live { margin-left: auto; font-size: 14px; color: var(--mw-color-text-secondary); }
.accumulation-picker, .accumulation-input { display: grid; gap: 8px; }
.accumulation-picker { max-width: 480px; }
.accumulation-input { max-width: 720px; }
label, dt { font-size: 14px; color: var(--mw-color-text-secondary); }
.accumulation-values { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(240px, 100%), 1fr)); gap: 16px; margin: 0; }
dd { margin: 4px 0 0; font-family: var(--mw-font-mono); overflow-wrap: anywhere; }
.accumulation-csv-review { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 240px; overflow-y: auto; }
.accumulation-history, .accumulation-panel :deep(.accumulation-replay) { border-top: 1px solid var(--mw-color-border); margin: 0; }
summary, .accumulation-panel :deep(.accumulation-replay > summary) { cursor: pointer; padding: 12px 0; margin: 0; min-height: 44px; font-size: 14px; color: var(--mw-color-text-primary); font-weight: 500; }
.accumulation-values dd { font-size: 20px; color: var(--mw-color-text-primary); }
.accumulation-history .accumulation-values dd { font-size: 16px; }
.accumulation-history > div, .accumulation-history > p, .accumulation-history > .accumulation-values { margin-bottom: 16px; }
.accumulation-panel :deep(.accumulation-replay > summary) { display: list-item; }
.accumulation-order-list { display: grid; gap: 16px; padding-left: 20px; }
.accumulation-order-list li { min-width: 0; overflow-wrap: anywhere; }
summary:focus-visible { outline: 2px solid var(--mw-color-primary); outline-offset: 3px; }
@media (max-width: 767px) {
  .accumulation-panel { padding: 16px; }
  .accumulation-panel :deep(.n-button), .accumulation-panel :deep(.n-base-selection), .accumulation-panel :deep(.n-input) { min-height: 44px; }
  .accumulation-actions { align-items: stretch; }
}
</style>
