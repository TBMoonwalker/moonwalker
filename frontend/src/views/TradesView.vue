<script setup lang="ts">
import {
  computed,
  defineAsyncComponent,
  ref,
} from 'vue'
import Statistics from '@/components/Statistics.vue'
import { formatAutopilotMemoryHint } from '@/autopilot/presentation'
import { useWebSocketDataStore } from '@/stores/websocket'
import { storeToRefs } from 'pinia'
import { useSharedConfigSnapshot } from '@/control-center/configSnapshotStore'
import { useTradingPauseStatus } from '@/composables/useTradingPauseStatus'
import { RouterLink } from 'vue-router'
import type { PerformanceRange } from '@/helpers/performanceRange'

const OpenTrades = defineAsyncComponent(() => import('../components/OpenTrades.vue'))
const ClosedTrades = defineAsyncComponent(() => import('../components/ClosedTrades.vue'))
const UnsellableTrades = defineAsyncComponent(() => import('../components/UnsellableTrades.vue'))
const UpnlChart = defineAsyncComponent(() => import('@/components/UpnlChart.vue'))
const Charts = defineAsyncComponent(() => import('@/components/Charts.vue'))

const unsellableTradesStore = useWebSocketDataStore('unsellableTrades')
const unsellableTradesState = storeToRefs(unsellableTradesStore)
const openTradesStore = useWebSocketDataStore('openTrades')
const openTradesState = storeToRefs(openTradesStore)
const closedTradesStore = useWebSocketDataStore('closedTrades')
const closedTradesState = storeToRefs(closedTradesStore)
const statisticsStore = useWebSocketDataStore('statistics')
const statisticsState = storeToRefs(statisticsStore)
const configSnapshotStore = useSharedConfigSnapshot()
const { tradingPaused } = useTradingPauseStatus()
const performanceRange = ref<PerformanceRange>('all')
const performanceRanges: { value: PerformanceRange; label: string }[] = [
  { value: 'all', label: 'ALL' },
  { value: '1d', label: '1D' },
  { value: '30d', label: '30D' },
  { value: '365d', label: '1Y' },
]
const profitPeriod = computed(() => ({
  '1d': 'daily',
  '30d': 'monthly',
  '365d': 'yearly',
}[performanceRange.value] ?? 'daily'))
const performanceDescription = computed(() => ({
  all: 'Cumulative profit and funds in deals',
  '1d': 'Daily closed-trade profit this month',
  '30d': 'Monthly closed-trade profit this year',
  '365d': 'Yearly closed-trade profit',
}[performanceRange.value]))
const activeTradeView = ref<'open' | 'closed' | 'unsellable'>('open')
const unsellableTradesCount = computed(() =>
  Array.isArray(unsellableTradesState.data.value) ? unsellableTradesState.data.value.length : 0
)
const openTradesCount = computed(() =>
  Array.isArray(openTradesState.data.value) ? openTradesState.data.value.length : 0,
)
const closedTradesCount = computed(() =>
  Array.isArray(closedTradesState.data.value) ? closedTradesState.data.value.length : 0,
)
const streamsConnected = computed(
  () => statisticsState.status.value === 'OPEN' && openTradesState.status.value === 'OPEN',
)
const autopilotPayload = computed(() => statisticsState.data.value as Record<string, unknown> | null)
const autopilotState = computed(() => String(autopilotPayload.value?.autopilot ?? 'none'))
const autopilotModeLabel = computed(() => {
  if (!statisticsState.hasReceivedData.value || !autopilotPayload.value) return 'Unavailable'
  if (!['high', 'medium', 'low'].includes(autopilotState.value)) return 'Disabled'
  return autopilotState.value.charAt(0).toUpperCase() + autopilotState.value.slice(1)
})
const autopilotTone = computed(() => ({
  high: 'red', medium: 'orange', low: 'green',
}[autopilotState.value] ?? 'muted'))
const autopilotSummary = computed(() =>
  ['high', 'medium', 'low'].includes(autopilotState.value)
    ? `Effective max bots ${safeNumber(autopilotPayload.value?.autopilot_effective_max_bots)}`
    : '',
)
const greenPhaseHint = computed(() => {
  const payload = autopilotPayload.value
  if (!payload || !['high', 'medium', 'low'].includes(autopilotState.value)) return ''
  const memoryStatus = typeof payload.autopilot_memory_status === 'string' ? payload.autopilot_memory_status : null
  const staleReason = typeof payload.autopilot_memory_stale_reason === 'string' ? payload.autopilot_memory_stale_reason : null
  if (payload.autopilot_memory_stale || memoryStatus === 'warming_up') {
    return formatAutopilotMemoryHint({
      currentCloses: safeNumber(payload.autopilot_memory_current_closes),
      requiredCloses: safeNumber(payload.autopilot_memory_required_closes),
      stale: Boolean(payload.autopilot_memory_stale),
      staleReason,
      status: memoryStatus,
    })
  }
  if (payload.autopilot_green_phase_active) {
    return `Green phase active (+${safeNumber(payload.autopilot_green_phase_extra_deals)} deals)`
  }
  if (payload.autopilot_green_phase_detected && typeof payload.autopilot_green_phase_block_reason === 'string') {
    return `Green phase blocked: ${payload.autopilot_green_phase_block_reason.replaceAll('_', ' ')}`
  }
  return 'Green phase idle'
})
function safeNumber(value: unknown): number {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : 0
}
type DelistingWarningRow = {
  symbol?: string
  delisting_warning?: boolean
  delisting_at?: string | null
  delisting_check_unavailable?: boolean
  delisting_check_message?: string | null
}
const delistingWarnings = computed(() => {
  if (!Array.isArray(openTradesState.data.value)) return []
  return (openTradesState.data.value as DelistingWarningRow[]).filter(
    (row) => Boolean(row.delisting_warning),
  )
})
const delistingWarningCopy = computed(() => {
  const affected = delistingWarnings.value.map((row) => {
    const symbol = String(row.symbol || 'Unknown symbol')
    if (!row.delisting_at) return `${symbol} (market inactive)`
    const timestamp = new Date(row.delisting_at)
    const formatted = Number.isNaN(timestamp.getTime())
      ? row.delisting_at
      : new Intl.DateTimeFormat(undefined, {
          dateStyle: 'medium',
          timeStyle: 'short',
        }).format(timestamp)
    return `${symbol} (${formatted})`
  })
  return `${affected.join(', ')}. New buys are blocked. Existing sell and take-profit orders remain active.`
})
const delistingCheckUnavailable = computed(() => {
  if (!Array.isArray(openTradesState.data.value)) return false
  return (openTradesState.data.value as DelistingWarningRow[]).some(
    (row) => Boolean(row.delisting_check_unavailable),
  )
})
const delistingCheckUnavailableCopy = computed(() => {
  if (!Array.isArray(openTradesState.data.value)) return ''
  const row = (openTradesState.data.value as DelistingWarningRow[]).find(
    (candidate) => Boolean(candidate.delisting_check_unavailable),
  )
  return row?.delisting_check_message ||
    `Moonwalker cannot verify the exchange delisting schedule. New buys are blocked. Existing sell and take-profit orders remain active.`
})
function configFlagEnabled(value: unknown): boolean {
  return value === true || value === 'true'
}

const aiTrustEnforcementActive = computed(
  () =>
    configFlagEnabled(configSnapshotStore.snapshot.value?.ai_trust_enabled) &&
    configFlagEnabled(configSnapshotStore.snapshot.value?.ai_trust_enforce_warnings)
)
const aiTrustRuntimeStatus = computed(() =>
  String(configSnapshotStore.snapshot.value?.ai_trust_runtime_status ?? 'ok')
)
const aiTrustRuntimeProviderStatus = computed(() =>
  String(configSnapshotStore.snapshot.value?.ai_trust_runtime_provider_status ?? '')
)
const aiTrustProviderUnavailable = computed(
  () =>
    aiTrustEnforcementActive.value &&
    aiTrustRuntimeStatus.value === 'provider_unavailable'
)
const aiTrustWarningBlocked = computed(
  () =>
    aiTrustEnforcementActive.value &&
    aiTrustRuntimeStatus.value === 'warning_blocked'
)
const tradeAdmissionWarning = computed(
  () =>
    delistingCheckUnavailable.value ||
    aiTrustProviderUnavailable.value ||
    aiTrustWarningBlocked.value
)
const admissionStatusLabel = computed(() => {
  if (tradingPaused.value) return 'Moonwalker paused'
  if (delistingCheckUnavailable.value) return 'Delisting check unavailable'
  if (aiTrustProviderUnavailable.value) return 'AI unavailable'
  if (aiTrustWarningBlocked.value) return 'AI blocked entry'
  if (!streamsConnected.value) return 'Entry status pending'
  return 'Moonwalker open'
})
const admissionStatusCopy = computed(() => {
  if (tradingPaused.value) {
    return 'New trades and re-entries are paused. Existing exits can keep running.'
  }
  if (delistingCheckUnavailable.value) {
    return `The exchange delisting schedule is unavailable. All new buys are blocked until verification succeeds. Existing exits can keep running.`
  }
  if (aiTrustProviderUnavailable.value) {
    const provider = aiTrustRuntimeProviderStatus.value || 'unscored'
    return `AI enforcement is active, but the local model did not return a scored response (${provider}). New entries are blocked until AI answers successfully.`
  }
  if (aiTrustWarningBlocked.value) {
    return 'AI enforcement blocked the latest warned entry. New entries continue only after AI returns no warning.'
  }
  if (!streamsConnected.value) {
    return 'Trade admission will be confirmed when live data arrives.'
  }
  return 'New trades and re-entries are currently allowed.'
})
const admissionStatusTagType = computed(() =>
  tradingPaused.value || tradeAdmissionWarning.value
    ? 'warning'
    : streamsConnected.value ? 'success' : 'info'
)
const admissionToneClass = computed(() =>
  tradingPaused.value || tradeAdmissionWarning.value || !streamsConnected.value
    ? 'is-warning'
    : 'is-open'
)

</script>

<template>
  <div class="page-shell trades-page operator-console-page">
    <header class="overview-heading">
      <div>
        <p class="overview-eyebrow">Operator console</p>
        <h1>Trading overview</h1>
        <p>Active deals, portfolio position, and system state in one place.</p>
      </div>
      <RouterLink class="overview-action" :to="{ name: 'stats' }">
        View statistics <span aria-hidden="true">↗</span>
      </RouterLink>
    </header>

    <n-alert
      v-if="delistingWarnings.length > 0"
      class="delisting-alert"
      title="Open trade affected by delisting"
      type="error"
      role="alert"
      aria-live="assertive"
    >
      {{ delistingWarningCopy }}
    </n-alert>

    <n-alert
      v-if="delistingCheckUnavailable"
      class="delisting-alert"
      title="Delisting protection cannot verify the exchange schedule"
      type="warning"
      role="alert"
      aria-live="assertive"
    >
      {{ delistingCheckUnavailableCopy }}
      Configure production read-only schedule credentials or enable trading
      credential reuse in Control Center → Signal source.
    </n-alert>

    <section
      class="dashboard-panel admission-strip moonwalker-status"
      :class="admissionToneClass"
      aria-labelledby="moonwalker-status-title"
      aria-live="polite"
    >
      <div class="status-main">
        <div class="status-heading">
          <h2 id="moonwalker-status-title">Moonwalker status</h2>
          <RouterLink :to="{ name: 'monitoring' }">Monitoring ↗</RouterLink>
        </div>
        <div class="status-state">
          <n-tag class="admission-pill" :type="admissionStatusTagType" :bordered="false">
            {{ admissionStatusLabel }}
          </n-tag>
          <span class="admission-copy">{{ admissionStatusCopy }}</span>
        </div>
      </div>
      <div class="status-autopilot">
        <h3>Autopilot</h3>
        <div class="status-autopilot-value" :class="autopilotTone">{{ autopilotModeLabel }}</div>
        <p v-if="autopilotSummary">{{ autopilotSummary }}</p>
        <p v-if="greenPhaseHint">{{ greenPhaseHint }}</p>
        <p v-if="!statisticsState.hasReceivedData.value || !autopilotPayload">Waiting for live status</p>
        <RouterLink :to="{ name: 'controlCenterAutopilot' }">Open Autopilot ↗</RouterLink>
      </div>
    </section>

    <div class="overview-middle">
    <section class="dashboard-panel chart-panel" aria-label="Performance chart">
      <div class="overview-panel-heading">
        <div>
          <h2>Performance</h2>
          <p>{{ performanceDescription }}</p>
        </div>
        <div class="range-switcher" role="group" aria-label="Performance range">
          <button
            v-for="range in performanceRanges"
            :key="range.value"
            type="button"
            :aria-pressed="performanceRange === range.value"
            :class="{ 'is-active': performanceRange === range.value }"
            @click="performanceRange = range.value"
          >
            {{ range.label }}
          </button>
        </div>
      </div>
      <UpnlChart v-if="performanceRange === 'all'" :range="performanceRange" />
      <Charts v-else :key="performanceRange" :period="profitPeriod" />
    </section>
    <section class="trades-metrics" aria-label="Portfolio exposure">
      <Statistics />
    </section>
    </div>

    <section class="overview-trades" aria-label="Trade records">
      <div class="trade-view-selector" role="group" aria-label="Trade records">
        <button type="button" :aria-pressed="activeTradeView === 'open'" :class="{ 'is-active': activeTradeView === 'open' }" @click="activeTradeView = 'open'">Open trades <span>{{ openTradesCount }}</span></button>
        <span class="trade-view-divider" aria-hidden="true">|</span>
        <button type="button" :aria-pressed="activeTradeView === 'closed'" :class="{ 'is-active': activeTradeView === 'closed' }" @click="activeTradeView = 'closed'">Closed trades <span>{{ closedTradesCount }}</span></button>
        <span class="trade-view-divider" aria-hidden="true">|</span>
        <button type="button" :aria-pressed="activeTradeView === 'unsellable'" :class="{ 'is-active': activeTradeView === 'unsellable' }" @click="activeTradeView = 'unsellable'">Unsellable trades <span>{{ unsellableTradesCount }}</span></button>
      </div>
      <div class="dashboard-panel ledger-panel trade-table-panel">
        <OpenTrades v-if="activeTradeView === 'open'" :global-trading-paused="tradingPaused" />
        <ClosedTrades v-else-if="activeTradeView === 'closed'" />
        <UnsellableTrades v-else />
      </div>
    </section>
  </div>
</template>

<style scoped>
.overview-heading {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 20px;
  margin-bottom: 2px;
}

.overview-eyebrow {
  margin: 0 0 8px;
  color: var(--mw-color-primary);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.15em;
  text-transform: uppercase;
}

.overview-heading h1 {
  margin: 0 0 8px;
  color: var(--mw-color-text-primary);
  font-family: var(--mw-font-display);
  font-size: clamp(25px, 2.5vw, 32px);
  font-weight: 600;
  letter-spacing: -0.045em;
  line-height: 1.1;
}

.overview-heading p:last-child {
  margin: 0;
  color: var(--mw-color-text-muted);
  font-size: 13px;
}

.overview-action {
  flex: none;
  display: inline-flex;
  align-items: center;
  min-height: 36px;
  padding: 0 14px;
  border: 1px solid var(--mw-color-primary);
  border-radius: 6px;
  background: var(--mw-color-primary);
  color: var(--mw-color-surface-base);
  font-size: 12px;
  font-weight: 700;
  text-decoration: none;
}

.overview-action:focus-visible,
.overview-section-heading a:focus-visible {
  outline: 2px solid var(--mw-color-primary);
  outline-offset: 3px;
}

.admission-strip {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(180px, 0.42fr);
  gap: 18px;
  padding: 14px 18px;
  border: 1px solid var(--mw-color-border);
  background: var(--mw-color-surface-panel);
  box-shadow: none;
}

.status-heading,
.status-state { display: flex; align-items: center; gap: 12px; }
.status-heading { justify-content: space-between; margin-bottom: 8px; }
.status-heading h2 { margin: 0; color: var(--mw-color-text-primary); font-size: 14px; font-weight: 600; }
.status-heading a { color: var(--mw-color-primary); font-size: 11px; font-weight: 600; text-decoration: none; }
.status-state { align-items: flex-start; flex-wrap: wrap; }
.admission-copy { flex: 1 1 220px; color: var(--mw-color-text-muted); font-size: 12px; line-height: 1.45; }
.status-autopilot { min-width: 0; padding-left: 18px; border-left: 1px solid var(--mw-color-border); }
.status-autopilot h3 { margin: 0 0 6px; color: var(--mw-color-text-primary); font-size: 12px; font-weight: 600; }
.status-autopilot-value { color: var(--mw-color-text-primary); font-family: var(--mw-font-display); font-size: 18px; font-weight: 600; line-height: 1; }
.status-autopilot-value.green { color: var(--mw-color-success); }
.status-autopilot-value.orange { color: var(--mw-color-warning); }
.status-autopilot-value.red { color: var(--mw-color-error); }
.status-autopilot-value.muted { color: var(--mw-color-text-muted); }
.status-autopilot p { margin: 5px 0 0; color: var(--mw-color-text-muted); font-size: 11px; line-height: 1.3; }
.status-autopilot a { display: inline-block; margin-top: 5px; color: var(--mw-color-primary); font-size: 11px; font-weight: 600; text-decoration: none; }
.status-autopilot a:focus-visible { outline: 2px solid var(--mw-color-primary); outline-offset: 3px; }

.trades-metrics {
  width: 100%;
  min-width: 0;
}

.overview-middle {
  display: grid;
  grid-template-columns: minmax(0, 1.65fr) minmax(290px, 0.85fr);
  align-items: stretch;
  gap: 14px;
  min-width: 0;
}

.overview-panel-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 19px 20px 12px;
}

.range-switcher {
  display: inline-flex;
  flex: none;
  gap: 2px;
  padding: 3px;
  border: 1px solid var(--mw-color-border);
  border-radius: 7px;
  background: var(--mw-surface-card-muted);
}

.range-switcher button {
  min-width: 42px;
  min-height: 28px;
  padding: 0 8px;
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: var(--mw-color-text-muted);
  font: 600 11px var(--mw-font-body);
  cursor: pointer;
}

.range-switcher button:hover { color: var(--mw-color-text-primary); }
.range-switcher button.is-active {
  background: var(--mw-color-surface-panel);
  color: var(--mw-color-primary);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.12);
}
.range-switcher button:focus-visible { outline: 2px solid var(--mw-color-primary); }

.overview-panel-heading h2,
.overview-section-heading h2 {
  margin: 0;
  color: var(--mw-color-text-primary);
  font-size: 14px;
  font-weight: 600;
}

.overview-panel-heading p {
  margin: 5px 0 0;
  color: var(--mw-color-text-muted);
  font-size: 11px;
}

.overview-trades {
  min-width: 0;
}

.trade-view-selector { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; margin-bottom: 10px; }
.trade-view-selector button { min-height: 36px; padding: 0 6px; border: 0; background: transparent; color: var(--mw-color-text-muted); font: 600 16px var(--mw-font-body); cursor: pointer; }
.trade-view-selector button.is-active { color: var(--mw-color-text-primary); }
.trade-view-selector button:hover { color: var(--mw-color-primary); }
.trade-view-selector button:focus-visible { outline: 2px solid var(--mw-color-primary); outline-offset: 2px; border-radius: 4px; }
.trade-view-selector button span { margin-left: 3px; color: var(--mw-color-text-muted); font-size: 13px; font-weight: 500; }
.trade-view-divider { color: var(--mw-color-border-strong); font-size: 16px; }

.trade-table-panel {
  overflow: visible;
  padding: 12px 16px 16px;
}

.trade-table-panel :deep(.n-data-table) {
  width: 100%;
  min-width: 0;
  font-family: var(--mw-font-body);
}

.trade-table-panel :deep(.n-data-table-td) {
  font-family: var(--mw-font-body);
  font-size: 13px;
}

.trade-table-panel :deep(.n-data-table-th) {
  border-bottom-color: var(--mw-color-border);
  font-family: var(--mw-font-body);
  font-size: 11px;
}

.overview-section-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-height: 32px;
  margin-bottom: 10px;
}

.overview-section-heading h2 {
  font-size: 16px;
}

.overview-section-heading h2 span {
  margin-left: 4px;
  color: var(--mw-color-text-muted);
  font-size: 13px;
  font-weight: 500;
}

.chart-panel {
  display: flex;
  flex-direction: column;
}

.chart-panel :deep(.chart-wrap) {
  flex: 1;
  min-height: 230px;
  border: 0;
  border-radius: 0;
  background: transparent;
}

.ledger-panel :deep(.trade-symbol-cell),
.ledger-panel :deep(.trade-cell-stack) {
  display: flex;
  flex-direction: column;
  gap: 5px;
  min-width: 0;
}

.ledger-panel :deep(.trade-symbol-main) {
  color: var(--mw-color-text-primary);
  font-family: var(--mw-font-body);
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0;
}

.ledger-panel :deep(.trade-symbol-meta) {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 5px;
  min-width: 0;
}

.ledger-panel :deep(.trade-cell-main) {
  color: var(--mw-color-text-primary);
  font-family: var(--mw-font-body);
  font-size: 13px;
  font-variant-numeric: tabular-nums;
  line-height: 1.2;
}

.ledger-panel :deep(.trade-cell-main.is-active) {
  color: var(--mw-color-success);
}

.ledger-panel :deep(.trade-cell-main.is-warning) {
  color: var(--mw-color-warning);
}

.ledger-panel :deep(.trade-cell-main.is-info) {
  color: var(--mw-color-info);
}

.ledger-panel :deep(.trade-cell-sub) {
  color: var(--mw-color-text-muted);
  font-family: var(--mw-font-body);
  font-size: 12px;
  line-height: 1.2;
}

.ledger-panel :deep(.trade-cell-tags) {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.ledger-panel :deep(.trade-tpso-cell) {
  display: inline-grid;
  justify-items: start;
  gap: 5px;
  min-width: 132px;
}

.ledger-panel :deep(.trade-tpso-track) {
  position: relative;
  width: 132px;
  height: 8px;
  overflow: hidden;
  border-radius: 999px;
  background: color-mix(in srgb, var(--mw-color-border) 72%, transparent);
}

.ledger-panel :deep(.trade-tpso-fill) {
  position: absolute;
  top: 0;
  bottom: 0;
  left: 0;
  border-radius: 999px;
  background: var(--mw-color-success);
}

.ledger-panel :deep(.trade-tpso-cell.is-negative .trade-tpso-fill) {
  background: var(--mw-color-error);
}

.ledger-panel :deep(.trade-tpso-cell.is-idle .trade-tpso-fill) {
  background: transparent;
}

.ledger-panel :deep(.trade-progress-label) {
  color: var(--mw-color-text-muted);
  font-family: var(--mw-font-body);
  font-size: 12px;
  line-height: 1.2;
}

.ledger-panel :deep(.trade-row-actions) {
  display: flex;
  justify-content: flex-end;
  gap: 7px;
}

.ledger-panel :deep(.trade-row-actions .n-button) {
  min-height: 36px !important;
  min-width: 48px !important;
  border-radius: 8px !important;
}

.ledger-panel :deep(.trade-expand-button) {
  color: var(--mw-color-primary);
}

@media (max-width: 700px) {
  .admission-strip { grid-template-columns: minmax(0, 1fr); }
  .status-autopilot { padding-left: 0; padding-top: 12px; border-left: 0; border-top: 1px solid var(--mw-color-border); }
}

@media (max-width: 980px) {
  .overview-middle { grid-template-columns: minmax(0, 1fr); }
}

@media (max-width: 650px) {
  .trade-view-selector { gap: 2px; }
  .trade-view-selector button { min-height: 44px; font-size: 13px; }
  .trade-view-selector button span { font-size: 12px; }
}

@media (max-width: 767px) {
  .overview-heading {
    align-items: flex-start;
  }

  .overview-action {
    display: none;
  }

  .overview-panel-heading {
    flex-wrap: wrap;
    padding: 16px 14px 10px;
  }

  .range-switcher { width: 100%; }
  .range-switcher button { flex: 1; min-height: 36px; }
  .trade-table-panel { padding: 8px 10px 10px; }

}

@media (max-width: 520px) {
  .ledger-panel :deep(.n-data-table-td),
  .ledger-panel :deep(.n-data-table-th) {
    padding-left: 6px !important;
    padding-right: 6px !important;
  }

  .ledger-panel :deep(.n-data-table-th[data-col-key="__n_expand__"]),
  .ledger-panel :deep(.n-data-table-td[data-col-key="__n_expand__"]) {
    width: 0 !important;
    min-width: 0 !important;
    max-width: 0 !important;
    padding: 0 !important;
    border: 0 !important;
    overflow: hidden;
  }

  .ledger-panel :deep(.n-data-table-table colgroup col:first-child) {
    width: 0 !important;
    min-width: 0 !important;
    max-width: 0 !important;
  }

  .ledger-panel :deep(.n-data-table-th[data-col-key="symbol"]),
  .ledger-panel :deep(.n-data-table-td[data-col-key="symbol"]) {
    min-width: 116px;
    width: 116px;
    max-width: 116px;
    padding-left: 0 !important;
    padding-right: 4px !important;
  }

  .ledger-panel :deep(.open-trades-table .n-data-table-th[data-col-key="symbol"]),
  .ledger-panel :deep(.open-trades-table .n-data-table-td[data-col-key="symbol"]) {
    min-width: 104px;
    width: 104px;
    max-width: 104px;
  }

  .ledger-panel :deep(.n-data-table-th[data-col-key="display_profit_percent"]),
  .ledger-panel :deep(.n-data-table-td[data-col-key="display_profit_percent"]) {
    min-width: 72px;
    width: 72px;
    max-width: 72px;
  }

  .ledger-panel :deep(.n-data-table-th[data-col-key="action"]),
  .ledger-panel :deep(.n-data-table-td[data-col-key="action"]) {
    min-width: 96px;
    width: 96px;
    max-width: 96px;
  }

  .ledger-panel :deep(.open-trades-table .n-data-table-th[data-col-key="action"]),
  .ledger-panel :deep(.open-trades-table .n-data-table-td[data-col-key="action"]) {
    min-width: 64px;
    width: 64px;
    max-width: 64px;
  }

  .ledger-panel :deep(.open-trades-table .n-data-table-th[data-col-key="open_date"]),
  .ledger-panel :deep(.open-trades-table .n-data-table-td[data-col-key="open_date"]) {
    min-width: 85px;
    width: 85px;
    max-width: 85px;
  }

  .ledger-panel :deep(.closed-trades-table .n-data-table-th[data-col-key="action"]),
  .ledger-panel :deep(.closed-trades-table .n-data-table-td[data-col-key="action"]) {
    min-width: 52px;
    width: 52px;
  }

  .ledger-panel :deep(.trade-symbol-main) {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .ledger-panel :deep(.n-data-table-td[data-col-key="display_profit_percent"] .trade-cell-main),
  .ledger-panel :deep(.n-data-table-td[data-col-key="display_profit_percent"] .trade-cell-sub) {
    white-space: nowrap;
  }

  .ledger-panel :deep(.trade-row-actions) {
    display: grid;
    grid-template-columns: repeat(2, 44px);
    justify-content: end;
    width: 92px;
    gap: 4px;
  }

  .ledger-panel :deep(.open-trades-table .trade-row-actions) {
    grid-template-columns: 44px;
    width: 44px;
  }

  .ledger-panel :deep(.trade-row-actions .n-button) {
    min-width: 44px !important;
    width: 44px !important;
    min-height: 44px !important;
    padding: 0 !important;
   }

  .ledger-panel :deep(.unsellable-trades .trade-row-actions) {
     display: flex;
     justify-content: center;
     width: 100%;
    }

  .ledger-panel :deep(.unsellable-trades .trade-row-actions .n-button) {
    min-width: 72px !important;
    width: auto !important;
    padding: 0 10px !important;
  }

  .ledger-panel :deep(.trade-row-actions .trade-action-more) {
    grid-column: 1 / -1;
    width: 92px !important;
  }

  .ledger-panel :deep(.open-trades-table .trade-row-actions .trade-action-more) {
    grid-column: auto;
    width: 44px !important;
  }

  .ledger-panel :deep(.trade-row-actions-delete) {
    display: flex;
    justify-content: center;
    width: 44px;
  }

  .ledger-panel :deep(.trade-action-label) {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip: rect(0 0 0 0);
    white-space: nowrap;
  }

   /* Paged feeds render Naive pagination internally; bump item boxes to 44px so
    Open/Closed/Unsellable match StatisticsView.vue, not the 28px Naive default. */
   .ledger-panel :deep(.n-pagination-item) {
     min-width: 44px;
     height: 44px;
   }

}
</style>
