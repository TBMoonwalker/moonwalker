<script setup lang="ts">
import {
  computed,
  defineAsyncComponent,
  nextTick,
  onMounted,
  onUnmounted,
  ref,
  type HTMLAttributes,
} from 'vue'
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
const openTradesStore = useWebSocketDataStore('openTrades')
const openTradesState = storeToRefs(openTradesStore)
const configSnapshotStore = useSharedConfigSnapshot()
const viewportWidth = ref(window.innerWidth)
const { tradingPaused } = useTradingPauseStatus()
const isMobile = computed(() => viewportWidth.value < 768)
const tabPadding = computed(() => (isMobile.value ? 12 : 20))
const activeProfitTab = ref('profit-overall')
const activeTradesTab = ref('open-trades')
const profitTabsSection = ref<HTMLElement | null>(null)
const tradeTabsSection = ref<HTMLElement | null>(null)
const unsellableTradesCount = computed(() =>
  Array.isArray(unsellableTradesState.data.value) ? unsellableTradesState.data.value.length : 0
)
const waitingCampaignsCount = computed(() =>
  Array.isArray(waitingCampaignsState.data.value) ? waitingCampaignsState.data.value.length : 0
)
type DelistingWarningRow = {
  symbol?: string
  delisting_warning?: boolean
  delisting_at?: string | null
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

function buildTabProps(
  group: 'profit' | 'trade',
  name: string,
  activeName: string,
): HTMLAttributes {
  const selected = activeName === name
  return {
    id: `${group}-tab-${name}`,
    role: 'tab',
    tabindex: selected ? 0 : -1,
    'aria-selected': String(selected),
    'aria-controls': `${group}-panel-${name}`,
    onKeydown: handleTabKeydown,
  }
}

function getProfitTabProps(name: string): HTMLAttributes {
  return buildTabProps('profit', name, activeProfitTab.value)
}

function getTradeTabProps(name: string): HTMLAttributes {
  return buildTabProps('trade', name, activeTradesTab.value)
}

function handleTabKeydown(event: KeyboardEvent): void {
  const currentTab = event.currentTarget as HTMLElement | null
  const tablist = currentTab?.closest<HTMLElement>('[role="tablist"]')
  if (!currentTab || !tablist) return

  const tabs = Array.from(
    tablist.querySelectorAll<HTMLElement>('[role="tab"]:not([aria-disabled="true"])'),
  )
  const currentIndex = tabs.indexOf(currentTab)
  if (currentIndex < 0) return

  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault()
    currentTab.click()
    return
  }

  let nextIndex: number | null = null
  if (event.key === 'ArrowRight') nextIndex = (currentIndex + 1) % tabs.length
  if (event.key === 'ArrowLeft') nextIndex = (currentIndex - 1 + tabs.length) % tabs.length
  if (event.key === 'Home') nextIndex = 0
  if (event.key === 'End') nextIndex = tabs.length - 1
  if (nextIndex === null) return

  event.preventDefault()
  const nextTab = tabs[nextIndex]
  nextTab.click()
  void nextTick(() => nextTab.focus())
}

function syncTablistRoles(): void {
  const groups = [
    { root: profitTabsSection.value, label: 'Profit chart range' },
    { root: tradeTabsSection.value, label: 'Trade state' },
  ]
  for (const { root, label } of groups) {
    const tablist = root?.querySelector<HTMLElement>('.n-tabs-nav')
    tablist?.setAttribute('role', 'tablist')
    tablist?.setAttribute('aria-label', label)
  }
}

onMounted(() => {
  window.addEventListener('resize', handleResize)
  void nextTick(syncTablistRoles)
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

    <section
      ref="profitTabsSection"
      class="dashboard-panel chart-panel"
      aria-label="Profit charts"
    >
      <n-tabs
        v-model:value="activeProfitTab"
        class="calm-tabs profit-tabs"
        type="line"
        size="large"
        :tabs-padding="tabPadding"
        pane-class="chart-pane"
      >
        <n-tab-pane
          id="profit-panel-profit-overall"
          name="profit-overall"
          tab="Overall"
          role="tabpanel"
          aria-labelledby="profit-tab-profit-overall"
          :tab-props="getProfitTabProps('profit-overall')"
        >
          <UpnlChart v-if="activeProfitTab === 'profit-overall'" />
        </n-tab-pane>
        <n-tab-pane
          id="profit-panel-daily-profit"
          name="daily-profit"
          tab="Daily"
          role="tabpanel"
          aria-labelledby="profit-tab-daily-profit"
          :tab-props="getProfitTabProps('daily-profit')"
        >
          <Charts v-if="activeProfitTab === 'daily-profit'" period="daily" />
        </n-tab-pane>
        <n-tab-pane
          id="profit-panel-monthly-profit"
          name="monthly-profit"
          tab="Monthly"
          role="tabpanel"
          aria-labelledby="profit-tab-monthly-profit"
          :tab-props="getProfitTabProps('monthly-profit')"
        >
          <Charts v-if="activeProfitTab === 'monthly-profit'" period="monthly" />
        </n-tab-pane>
        <n-tab-pane
          id="profit-panel-yearly-profit"
          name="yearly-profit"
          tab="Yearly"
          role="tabpanel"
          aria-labelledby="profit-tab-yearly-profit"
          :tab-props="getProfitTabProps('yearly-profit')"
        >
          <Charts v-if="activeProfitTab === 'yearly-profit'" period="yearly" />
        </n-tab-pane>
      </n-tabs>
    </section>

    <section
      ref="tradeTabsSection"
      class="dashboard-panel ledger-panel"
      aria-label="Trades"
    >
      <n-tabs
        v-model:value="activeTradesTab"
        class="calm-tabs ledger-tabs"
        type="line"
        size="large"
        :tabs-padding="tabPadding"
      >
        <n-tab-pane
          id="trade-panel-open-trades"
          name="open-trades"
          role="tabpanel"
          aria-labelledby="trade-tab-open-trades"
          :tab-props="getTradeTabProps('open-trades')"
        >
          <template #tab>
            <span class="trade-tab-label">{{ isMobile ? 'Open' : 'Open Trades' }}</span>
          </template>
          <OpenTrades
            v-if="activeTradesTab === 'open-trades'"
            :global-trading-paused="tradingPaused"
          />
        </n-tab-pane>
        <n-tab-pane
          id="trade-panel-waiting-campaigns"
          name="waiting-campaigns"
          role="tabpanel"
          aria-labelledby="trade-tab-waiting-campaigns"
          :tab-props="getTradeTabProps('waiting-campaigns')"
        >
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
        <n-tab-pane
          id="trade-panel-unsellable-trades"
          name="unsellable-trades"
          role="tabpanel"
          aria-labelledby="trade-tab-unsellable-trades"
          :tab-props="getTradeTabProps('unsellable-trades')"
        >
          <template #tab>
            <span class="trade-tab-label" :class="{ 'trade-tab-label-warning': unsellableTradesCount > 0 }">
              <span>{{ isMobile ? 'Unsell.' : 'Unsellable' }}</span>
              <span v-if="unsellableTradesCount > 0" class="trade-tab-count">{{ unsellableTradesCount }}</span>
            </span>
          </template>
          <UnsellableTrades v-if="activeTradesTab === 'unsellable-trades'" />
        </n-tab-pane>
        <n-tab-pane
          id="trade-panel-closed-trades"
          name="closed-trades"
          role="tabpanel"
          aria-labelledby="trade-tab-closed-trades"
          :tab-props="getTradeTabProps('closed-trades')"
        >
          <template #tab>
            <span class="trade-tab-label">{{ isMobile ? 'Closed' : 'Closed Trades' }}</span>
          </template>
          <ClosedTrades v-if="activeTradesTab === 'closed-trades'" />
        </n-tab-pane>
      </n-tabs>
    </section>
  </div>
</template>

<style scoped>
.trades-metrics {
  width: 100%;
}

.trades-metrics :deep(.n-alert) {
  display: none;
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

@media (max-width: 768px) {
  .chart-panel :deep(.chart-wrap),
  .chart-panel :deep(.chart),
  .chart-panel :deep(.chart-placeholder) {
    height: 240px !important;
    min-height: 240px;
  }
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

  .ledger-panel :deep(.open-trades-table .n-data-table-table colgroup col:nth-child(1)) {
    width: 104px !important;
    min-width: 104px !important;
    max-width: 104px !important;
  }

  .ledger-panel :deep(.open-trades-table .n-data-table-table colgroup col:nth-child(2)) {
    width: 72px !important;
    min-width: 72px !important;
    max-width: 72px !important;
  }

  .profit-tabs :deep(.n-tabs-wrapper) {
    display: flex;
    width: 100%;
  }

  .ledger-tabs :deep(.n-tabs-wrapper) {
    display: flex;
    width: 100%;
  }

  .profit-tabs :deep(.n-tabs-tab-wrapper),
  .ledger-tabs :deep(.n-tabs-tab-wrapper) {
    flex: 1 1 0;
    min-width: 0;
  }

  .profit-tabs :deep(.n-tabs-tab),
  .ledger-tabs :deep(.n-tabs-tab) {
    justify-content: center;
    width: 100%;
  }

  .ledger-tabs :deep(.n-tabs-tab) {
    padding-left: 4px;
    padding-right: 4px;
  }

  .ledger-tabs .trade-tab-label {
    min-width: 0;
    max-width: 100%;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
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

  .ledger-panel :deep(.open-trades-table .n-data-table-table colgroup col:nth-child(3)) {
    width: 85px !important;
    min-width: 85px !important;
    max-width: 85px !important;
  }

  .ledger-panel :deep(.open-trades-table .n-data-table-table colgroup col:nth-child(4)) {
    width: 64px !important;
    min-width: 64px !important;
    max-width: 64px !important;
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

}
</style>
