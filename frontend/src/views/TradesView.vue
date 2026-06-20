<script setup lang="ts">
import { computed, defineAsyncComponent, onMounted, onUnmounted, ref } from 'vue'
import Statistics from '@/components/Statistics.vue'
import { useWebSocketDataStore } from '@/stores/websocket'
import { storeToRefs } from 'pinia'
import { useSharedConfigSnapshot } from '@/control-center/configSnapshotStore'
import { useTradingPauseStatus } from '@/composables/useTradingPauseStatus'

const OpenTrades = defineAsyncComponent(() => import('../components/OpenTrades.vue'))
const WaitingCampaigns = defineAsyncComponent(() => import('../components/WaitingCampaigns.vue'))
const ClosedTrades = defineAsyncComponent(() => import('../components/ClosedTrades.vue'))
const UnsellableTrades = defineAsyncComponent(() => import('../components/UnsellableTrades.vue'))
const Charts = defineAsyncComponent(() => import('@/components/Charts.vue'))
const UpnlChart = defineAsyncComponent(() => import('@/components/UpnlChart.vue'))

const unsellableTradesStore = useWebSocketDataStore('unsellableTrades')
const unsellableTradesState = storeToRefs(unsellableTradesStore)
const waitingCampaignsStore = useWebSocketDataStore('waitingCampaigns')
const waitingCampaignsState = storeToRefs(waitingCampaignsStore)
const configSnapshotStore = useSharedConfigSnapshot()
const viewportWidth = ref(window.innerWidth)
const { tradingPaused } = useTradingPauseStatus()
const isMobile = computed(() => viewportWidth.value < 768)
const tabPadding = computed(() => (isMobile.value ? 12 : 20))
const activeProfitTab = ref('profit-overall')
const activeTradesTab = ref('open-trades')
const unsellableTradesCount = computed(() =>
  Array.isArray(unsellableTradesState.data.value) ? unsellableTradesState.data.value.length : 0
)
const waitingCampaignsCount = computed(() =>
  Array.isArray(waitingCampaignsState.data.value) ? waitingCampaignsState.data.value.length : 0
)
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
  () => aiTrustProviderUnavailable.value || aiTrustWarningBlocked.value
)
const admissionStatusLabel = computed(() => {
  if (tradingPaused.value) return 'Moonwalker paused'
  if (aiTrustProviderUnavailable.value) return 'AI unavailable'
  if (aiTrustWarningBlocked.value) return 'AI blocked entry'
  return 'Moonwalker open'
})
const admissionStatusCopy = computed(() => {
  if (tradingPaused.value) {
    return 'New trades and re-entries are paused. Existing exits can keep running.'
  }
  if (aiTrustProviderUnavailable.value) {
    const provider = aiTrustRuntimeProviderStatus.value || 'unscored'
    return `AI enforcement is active, but the local model did not return a scored response (${provider}). New entries are blocked until AI answers successfully.`
  }
  if (aiTrustWarningBlocked.value) {
    return 'AI enforcement blocked the latest warned entry. New entries continue only after AI returns no warning.'
  }
  return 'New trades and re-entries are currently allowed.'
})
const admissionStatusTagType = computed(() =>
  tradingPaused.value || tradeAdmissionWarning.value ? 'warning' : 'success'
)
const admissionToneClass = computed(() =>
  tradingPaused.value || tradeAdmissionWarning.value ? 'is-warning' : 'is-open'
)

function handleResize() {
  viewportWidth.value = window.innerWidth
}

onMounted(() => {
  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
})
</script>

<template>
  <div class="page-shell trades-page operator-console-page">
    <section class="page-section trades-metrics" aria-label="Trade metrics">
      <Statistics />
    </section>

    <section
      class="admission-strip"
      :class="admissionToneClass"
      aria-live="polite"
    >
      <n-tag
        class="admission-pill"
        :type="admissionStatusTagType"
        :bordered="false"
      >
        {{ admissionStatusLabel }}
      </n-tag>
      <span class="admission-copy">
        {{ admissionStatusCopy }}
        <template v-if="!tradingPaused && !tradeAdmissionWarning">
          Queue counts live only in the trade tabs below.
        </template>
      </span>
    </section>

    <section class="dashboard-panel chart-panel" aria-label="Profit charts">
      <n-tabs
        v-model:value="activeProfitTab"
        class="calm-tabs profit-tabs"
        type="line"
        size="large"
        :tabs-padding="tabPadding"
        pane-class="chart-pane"
      >
        <n-tab-pane name="profit-overall" tab="Overall">
          <UpnlChart v-if="activeProfitTab === 'profit-overall'" />
        </n-tab-pane>
        <n-tab-pane name="daily-profit" tab="Daily">
          <Charts v-if="activeProfitTab === 'daily-profit'" period="daily" />
        </n-tab-pane>
        <n-tab-pane name="monthly-profit" tab="Monthly">
          <Charts v-if="activeProfitTab === 'monthly-profit'" period="monthly" />
        </n-tab-pane>
        <n-tab-pane name="yearly-profit" tab="Yearly">
          <Charts v-if="activeProfitTab === 'yearly-profit'" period="yearly" />
        </n-tab-pane>
      </n-tabs>
    </section>

    <section class="dashboard-panel ledger-panel" aria-labelledby="trade-ledger-title">
      <n-tabs
        v-model:value="activeTradesTab"
        class="calm-tabs ledger-tabs"
        type="line"
        size="large"
        :tabs-padding="tabPadding"
      >
        <n-tab-pane name="open-trades">
          <template #tab>
            <span id="trade-ledger-title" class="trade-tab-label">Open Trades</span>
          </template>
          <OpenTrades
            v-if="activeTradesTab === 'open-trades'"
            :global-trading-paused="tradingPaused"
          />
        </n-tab-pane>
        <n-tab-pane name="waiting-campaigns">
          <template #tab>
            <span class="trade-tab-label" :class="{ 'trade-tab-label-warning': waitingCampaignsCount > 0 }">
              <span>Waiting</span>
              <span v-if="waitingCampaignsCount > 0" class="trade-tab-count">{{ waitingCampaignsCount }}</span>
            </span>
          </template>
          <WaitingCampaigns
            v-if="activeTradesTab === 'waiting-campaigns'"
            :global-trading-paused="tradingPaused"
          />
        </n-tab-pane>
        <n-tab-pane name="unsellable-trades">
          <template #tab>
            <span class="trade-tab-label" :class="{ 'trade-tab-label-warning': unsellableTradesCount > 0 }">
              <span>Unsellable</span>
              <span v-if="unsellableTradesCount > 0" class="trade-tab-count">{{ unsellableTradesCount }}</span>
            </span>
          </template>
          <UnsellableTrades v-if="activeTradesTab === 'unsellable-trades'" />
        </n-tab-pane>
        <n-tab-pane name="closed-trades" tab="Closed Trades">
          <ClosedTrades v-if="activeTradesTab === 'closed-trades'" />
        </n-tab-pane>
      </n-tabs>
    </section>
  </div>
</template>

<style scoped>
.trades-page {
  gap: 12px;
  max-width: 1392px;
}

.page-section {
  min-width: 0;
}

.trades-metrics {
  width: 100%;
}

.trades-metrics :deep(.n-alert) {
  display: none;
}

.admission-strip {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: center;
  gap: 12px;
  min-width: 0;
  padding: 16px;
  border: 1px solid rgba(29, 92, 73, 0.14);
  border-radius: var(--mw-radius-md);
  background: rgba(29, 92, 73, 0.05);
  box-shadow: var(--mw-shadow-card);
}

.admission-strip.is-warning {
  border-color: rgba(183, 138, 46, 0.24);
  background: rgba(183, 138, 46, 0.08);
}

.admission-pill {
  width: max-content;
}

.admission-copy {
  color: var(--mw-color-text-secondary);
  font-size: 0.92rem;
  line-height: 1.35;
}

.dashboard-panel {
  position: relative;
  min-width: 0;
  overflow: hidden;
  border: 1px solid var(--mw-color-border);
  border-radius: var(--mw-radius-md);
  background: var(--mw-color-surface-panel);
  box-shadow: var(--mw-shadow-card);
  color: var(--mw-color-text-primary);
}

.chart-panel :deep(.n-tabs-nav) {
  min-height: 58px;
  padding-inline: 16px;
  border-bottom: 0;
}

.chart-panel :deep(.n-tab-pane) {
  padding: 0 16px 16px;
}

.chart-panel :deep(.n-tabs-nav-scroll-wrapper) {
  box-shadow: none;
}

.chart-panel :deep(.chart-wrap) {
  height: 190px;
  min-height: 190px;
  overflow: hidden;
  border: 1px solid var(--mw-color-border);
  border-radius: 9px;
  background: linear-gradient(180deg, var(--mw-color-surface-panel), var(--mw-surface-card-muted));
}

.chart-panel :deep(.chart),
.chart-panel :deep(.chart-placeholder) {
  height: 190px !important;
  min-height: 190px;
}

.ledger-panel :deep(.n-tabs-nav) {
  min-height: 74px;
  padding-inline: 16px;
  border-bottom: 0;
}

.ledger-panel :deep(.n-tab-pane) {
  padding: 0 16px 16px;
}

.calm-tabs :deep(.n-tabs-tab) {
  position: relative;
  min-height: 36px;
  padding: 8px 6px;
  border: 0;
  border-radius: 0;
  background: transparent;
  color: var(--mw-color-text-secondary);
  font-weight: 400;
}

.calm-tabs :deep(.n-tabs-wrapper) {
  display: flex;
  gap: 8px;
}

.calm-tabs :deep(.n-tabs-nav),
.calm-tabs :deep(.n-tabs-nav-scroll-wrapper),
.calm-tabs :deep(.n-tabs-nav-scroll-content),
.calm-tabs :deep(.n-tabs-wrapper),
.calm-tabs :deep(.n-tabs-tab-wrapper),
.calm-tabs :deep(.n-tabs-tab) {
  border-bottom: 0 !important;
  box-shadow: none !important;
}

.calm-tabs :deep(.n-tabs-nav::before),
.calm-tabs :deep(.n-tabs-nav::after),
.calm-tabs :deep(.n-tabs-nav-scroll-wrapper::before),
.calm-tabs :deep(.n-tabs-nav-scroll-wrapper::after),
.calm-tabs :deep(.n-tabs-nav-scroll-content::before),
.calm-tabs :deep(.n-tabs-nav-scroll-content::after),
.calm-tabs :deep(.n-tabs-wrapper::before),
.calm-tabs :deep(.n-tabs-wrapper::after) {
  display: none !important;
  content: none !important;
}

.calm-tabs :deep(.n-tabs-scroll-padding),
.calm-tabs :deep(.n-tabs-tab-pad) {
  display: none;
}

.calm-tabs :deep(.n-tabs-tab--active) {
  background: transparent;
  color: var(--mw-color-primary);
}

.calm-tabs :deep(.n-tabs-tab--active::after) {
  position: absolute;
  right: 6px;
  bottom: 0;
  left: 6px;
  height: 2px;
  border-radius: 999px;
  background: var(--mw-color-primary);
  content: "";
}

.calm-tabs :deep(.n-tabs-bar) {
  display: none;
}

.calm-tabs :deep(.n-tabs-tab__label) {
  font-weight: 450;
}

.chart-pane {
  min-width: 0;
}

.trade-tab-label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-weight: 450;
}

.trade-tab-label-warning {
  color: var(--mw-color-warning);
}

.trade-tab-count {
  display: inline-flex;
  align-items: center;
  min-width: 20px;
  justify-content: center;
  padding: 2px 7px;
  border-radius: 999px;
  background: rgba(183, 138, 46, 0.14);
  color: var(--mw-color-warning);
  font-family: var(--mw-font-mono);
  font-size: 12px;
  font-weight: 400;
  line-height: 1.2;
}

.ledger-panel :deep(.n-data-table) {
  --n-th-font-weight: 500;
  --n-font-size: 14px;
}

.ledger-panel :deep(.n-data-table-wrapper) {
  border: 0;
}

.ledger-panel :deep(.n-data-table-base-table) {
  overflow: hidden;
  border-radius: 9px;
}

.ledger-panel :deep(.n-data-table-th) {
  height: 44px;
  background: var(--mw-color-surface-panel);
  border-top: 0;
  color: var(--mw-color-text-muted);
  font-size: 12px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.ledger-panel :deep(.n-data-table-td) {
  font-family: var(--mw-font-mono);
  font-variant-numeric: tabular-nums;
  padding: 13px 12px;
  background: var(--mw-color-surface-panel);
  border-bottom-color: rgba(213, 219, 213, 0.7);
  vertical-align: middle;
}

.ledger-panel
  :deep(.n-data-table-tr--expanded:not(.trade-row-clickable) > .n-data-table-td[colspan]) {
  padding-inline: 12px;
}

.ledger-panel :deep(.n-data-table-tr:hover .n-data-table-td) {
  background: var(--mw-surface-card-muted);
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
  font-size: 16px;
  font-weight: 500;
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
  font-size: 14px;
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

.ledger-panel :deep(.trade-tpso-cell.is-warning .trade-tpso-fill) {
  background: var(--mw-color-warning);
}

.ledger-panel :deep(.trade-tpso-cell.is-idle .trade-tpso-fill) {
  background: transparent;
}

.ledger-panel :deep(.trade-progress-label) {
  color: var(--mw-color-text-muted);
  font-family: var(--mw-font-mono);
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

.ledger-panel :deep(.n-divider) {
  display: none;
}

@media (max-width: 768px) {
  .trades-page {
    gap: 10px;
  }

  .admission-strip {
    align-items: flex-start;
    grid-template-columns: 1fr;
  }

  .chart-panel :deep(.n-tabs-nav),
  .ledger-panel :deep(.n-tabs-nav) {
    padding-inline: 12px;
  }

  .chart-panel :deep(.n-tab-pane) {
    padding-inline: 12px;
  }

  .ledger-panel :deep(.n-tab-pane) {
    padding: 0 12px 12px;
  }

  .chart-panel :deep(.chart-wrap),
  .chart-panel :deep(.chart),
  .chart-panel :deep(.chart-placeholder) {
    height: 240px !important;
    min-height: 240px;
  }
}

@media (max-width: 520px) {
  .admission-strip,
  .dashboard-panel {
    border-radius: var(--mw-radius-sm);
  }

  .profit-tabs :deep(.n-tabs-wrapper) {
    display: flex;
    width: 100%;
  }

  .profit-tabs :deep(.n-tabs-tab-wrapper) {
    flex: 1 1 0;
    min-width: 0;
  }

  .profit-tabs :deep(.n-tabs-tab) {
    justify-content: center;
    width: 100%;
  }

  .calm-tabs :deep(.n-tabs-tab) {
    padding-inline: 10px;
    white-space: normal;
  }

  .ledger-panel :deep(.n-data-table-th),
  .ledger-panel :deep(.n-data-table-td) {
    padding-inline: 6px;
  }

  .ledger-panel :deep(.n-data-table-th[data-col-key="symbol"]),
  .ledger-panel :deep(.n-data-table-td[data-col-key="symbol"]) {
    min-width: 112px;
    width: 112px;
  }

  .ledger-panel :deep(.n-data-table-th[data-col-key="display_profit_percent"]),
  .ledger-panel :deep(.n-data-table-td[data-col-key="display_profit_percent"]) {
    min-width: 76px;
    width: 76px;
  }

  .ledger-panel :deep(.n-data-table-th[data-col-key="action"]),
  .ledger-panel :deep(.n-data-table-td[data-col-key="action"]) {
    min-width: 128px;
    width: 128px;
  }

  .ledger-panel :deep(.trade-symbol-main) {
    white-space: nowrap;
  }

  .ledger-panel :deep(.n-data-table-td[data-col-key="display_profit_percent"] .trade-cell-main),
  .ledger-panel :deep(.n-data-table-td[data-col-key="display_profit_percent"] .trade-cell-sub) {
    white-space: nowrap;
  }

  .ledger-panel :deep(.trade-row-actions) {
    flex-wrap: wrap;
    justify-content: flex-start;
    width: 116px;
    gap: 6px;
  }

  .ledger-panel :deep(.trade-row-actions .n-button) {
    min-height: 44px !important;
  }

  .ledger-panel :deep(.trade-row-actions .n-button:nth-child(n + 3)) {
    flex: 1 1 100%;
  }

}
</style>
