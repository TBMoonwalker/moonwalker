<template>
  <section
    v-if="visible"
    class="dashboard-panel placement-recovery"
    aria-label="Placement recovery"
    aria-live="polite"
  >
    <div class="placement-recovery-heading">
      <h2>Placement recovery</h2>
      <n-tag v-if="loadError" type="error" :bordered="false">Status unknown</n-tag>
      <n-tag v-else type="warning" :bordered="false">Startup gate closed</n-tag>
    </div>
    <p v-if="loadError" class="placement-recovery-lead">
      The quarantined placement list could not be loaded, so it is unknown whether the
      startup gate is blocked. Retry the load, or restart Moonwalker and check the logs
      if the error persists.
    </p>
    <p v-else class="placement-recovery-lead">
      {{ openCount }} placement {{ openCount === 1 ? 'intent is' : 'intents are' }} blocking
      startup. Repair checks the exchange and applies the confirmed state locally; dismissal
      records your decision without touching the exchange. Restart Moonwalker once every intent
      is resolved.
    </p>
    <p v-if="loading" class="placement-recovery-note">Loading quarantined placements…</p>
    <template v-else-if="loadError">
      <p class="placement-recovery-error" role="alert">
        Could not load quarantined placements: {{ loadError }}
      </p>
      <div class="placement-recovery-actions">
        <n-button size="small" type="primary" :loading="loading" @click="void load()">
          Retry
        </n-button>
      </div>
    </template>
    <ul v-else-if="intents.length > 0" class="placement-recovery-list">
      <li
        v-for="intent in intents"
        :key="intent.operation_id"
        class="placement-recovery-intent"
      >
        <div class="intent-head">
          <span class="intent-main">
            <strong>{{ intent.symbol }}</strong>
            <span class="intent-action">{{ actionLabel(intent) }}</span>
            <span v-if="!intent.has_lookup_identity" class="intent-flag">no exchange order identity</span>
          </span>
          <n-tag
            :type="intent.state === 'quarantined' ? 'warning' : 'info'"
            :bordered="false"
          >
            {{ intent.state === 'quarantined' ? 'Quarantined' : 'Restored quarantined' }}
          </n-tag>
        </div>
        <p v-if="intent.exchange_order_id" class="intent-reason">
          Exchange order ID: {{ intent.exchange_order_id }}
        </p>
        <p v-if="intent.client_order_id" class="intent-reason">
          Client order ID: {{ intent.client_order_id }}
        </p>
        <p class="intent-reason">{{ intent.error_message || intent.reason_code || 'No reason recorded.' }}</p>
        <p
          v-if="resultFor(intent)"
          class="intent-result"
          :class="`is-${resultFor(intent)!.status}`"
          role="status"
        >
          <strong>{{ resultLabel(resultFor(intent)!.status) }}</strong>
          {{ resultFor(intent)!.message }}
        </p>
        <div v-if="actionsVisibleFor(intent)" class="intent-actions">
          <n-button
            size="small"
            type="primary"
            :loading="stateFor(intent).pending"
            @click="void repair(intent.operation_id)"
          >
            Repair
          </n-button>
          <n-button
            size="small"
            type="warning"
            :disabled="stateFor(intent).pending"
            :data-dismiss-trigger="intent.operation_id"
            @click="openDismissForm(intent.operation_id)"
          >
            Dismiss…
          </n-button>
        </div>
        <div v-if="dismissing === intent.operation_id" class="dismiss-form">
          <label class="dismiss-label" :for="`dismiss-note-${intent.operation_id}`">
            Reason for dismissal
          </label>
          <input
            :id="`dismiss-note-${intent.operation_id}`"
            v-model="dismissNote"
            class="dismiss-input"
            type="text"
            maxlength="2000"
            placeholder="Record why this placement is safe to close (required)"
          />
          <div class="dismiss-actions">
            <n-button
              size="small"
              type="warning"
              :loading="stateFor(intent).pending"
              :disabled="!dismissNote.trim()"
              @click="void dismiss(intent.operation_id)"
            >
              Dismiss intent
            </n-button>
            <n-button size="small" quaternary :disabled="stateFor(intent).pending" @click="closeDismissForm()">
              Cancel
            </n-button>
          </div>
        </div>
        <p v-if="stateFor(intent).error" class="intent-error" role="alert">
          {{ stateFor(intent).error }}
        </p>
      </li>
    </ul>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted } from 'vue'
import { usePlacementRecovery } from '../composables/usePlacementRecovery'
import type { PlacementRecoveryActionState } from '../composables/usePlacementRecovery'
import type {
  PlacementRecoveryActionStatus,
  PlacementRecoveryIntent,
} from '../types/placementRecovery'

const {
  intents,
  loading,
  loadError,
  actions,
  dismissing,
  dismissNote,
  load,
  repair,
  openDismiss,
  closeDismiss,
  dismiss,
} = usePlacementRecovery()

// The card only exists to unblock a locked instance: with no quarantined
// intents and no load failure there is nothing to show.
const visible = computed(() => intents.value.length > 0 || loadError.value !== '')
const openCount = computed(() => intents.value.filter(
  (intent) => {
    const result = actions.get(intent.operation_id)?.last
    return !result || result.status === 'unchanged'
  },
).length)

const idleState: PlacementRecoveryActionState = { pending: false, error: '', last: null }

function stateFor(intent: PlacementRecoveryIntent): PlacementRecoveryActionState {
  return actions.get(intent.operation_id) ?? idleState
}

function resultFor(intent: PlacementRecoveryIntent) {
  return stateFor(intent).last
}

function actionsVisibleFor(intent: PlacementRecoveryIntent): boolean {
  const result = resultFor(intent)
  return !result || result.status === 'unchanged'
}

function actionLabel(intent: PlacementRecoveryIntent): string {
  const base = intent.action.replaceAll('_', ' ')
  const words = base.charAt(0).toUpperCase() + base.slice(1)
  const baseCurrency = intent.symbol.split('/')[0] ?? ''
  const quote = intent.symbol.split('/')[1] ?? ''
  const pieces = [words]
  if (intent.amount != null) {
    pieces.push(`${formatNumber(intent.amount)} ${baseCurrency}`.trim())
  }
  if (intent.limit_price != null && quote) {
    pieces.push(`@ ${formatNumber(intent.limit_price)} ${quote}`)
  }
  return pieces.join(' ')
}

function resultLabel(status: PlacementRecoveryActionStatus): string {
  return {
    completed: 'Resolved',
    rejected: 'Rejected',
    unchanged: 'Still quarantined',
    dismissed: 'Dismissed',
  }[status]
}

function formatNumber(value: number): string {
  return String(value)
}

// Keyboard flow: opening the form moves focus to the required note, and
// cancelling hands focus back to the trigger instead of dropping it on body.
function openDismissForm(operationId: string): void {
  openDismiss(operationId)
  void nextTick().then(() => {
    document.getElementById(`dismiss-note-${operationId}`)?.focus()
  })
}

function closeDismissForm(): void {
  const openId = dismissing.value
  closeDismiss()
  void nextTick().then(() => {
    const trigger = Array.from(
      document.querySelectorAll<HTMLElement>('[data-dismiss-trigger]'),
    ).find(element => element.getAttribute('data-dismiss-trigger') === openId)
    trigger?.focus()
  })
}

onMounted(() => { void load() })
</script>

<style scoped>
.placement-recovery {
  margin: 16px 0;
  padding: 16px;
}
.placement-recovery-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.placement-recovery-heading h2 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  letter-spacing: normal;
}
.placement-recovery-lead {
  margin: 8px 0 0;
  font-size: 14px;
  color: var(--mw-color-text-secondary);
}
.placement-recovery-note {
  margin: 12px 0 0;
  font-size: 14px;
  color: var(--mw-color-text-muted);
}
.placement-recovery-error {
  margin: 12px 0 0;
  font-size: 14px;
  color: var(--mw-color-error);
}
.placement-recovery-actions {
  margin-top: 12px;
}
.placement-recovery-list {
  list-style: none;
  margin: 12px 0 0;
  padding: 0;
  display: grid;
  gap: 12px;
}
.placement-recovery-intent {
  border: 1px solid var(--mw-color-border);
  border-radius: var(--mw-radius-sm);
  padding: 12px;
}
.intent-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.intent-main {
  display: inline-flex;
  align-items: baseline;
  gap: 8px;
  flex-wrap: wrap;
}
.intent-main strong {
  font-size: 14px;
  font-weight: 600;
}
.intent-action {
  font-family: var(--mw-font-mono);
  font-size: 14px;
  font-variant-numeric: tabular-nums;
  color: var(--mw-color-text-secondary);
}
.intent-flag {
  font-size: 12px;
  color: var(--mw-color-warning);
}
.intent-reason {
  margin: 8px 0 0;
  font-size: 14px;
  color: var(--mw-color-text-secondary);
  overflow-wrap: anywhere;
}
.intent-result {
  margin: 8px 0 0;
  font-size: 14px;
}
.intent-result.is-completed {
  color: var(--mw-color-success);
}
.intent-result.is-rejected,
.intent-result.is-dismissed {
  color: var(--mw-color-warning);
}
.intent-result.is-unchanged {
  color: var(--mw-color-text-secondary);
}
.intent-actions,
.dismiss-actions {
  display: flex;
  gap: 8px;
  margin-top: 12px;
}
.dismiss-form {
  margin-top: 12px;
}
.dismiss-label {
  display: block;
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 4px;
}
.dismiss-input {
  width: 100%;
  box-sizing: border-box;
  padding: 8px 12px;
  font-size: 14px;
  border: 1px solid var(--mw-color-border);
  border-radius: var(--mw-radius-sm);
  background: var(--mw-color-surface-panel);
  color: var(--mw-color-text-primary);
}
.dismiss-input:focus-visible {
  outline: 2px solid var(--mw-color-primary);
  outline-offset: 1px;
}
.intent-error {
  margin: 8px 0 0;
  font-size: 14px;
  color: var(--mw-color-error);
  overflow-wrap: anywhere;
}
@media (max-width: 767px) {
  .intent-actions .n-button,
  .dismiss-actions .n-button,
  .placement-recovery-actions .n-button {
    min-height: 44px;
  }
}
</style>
