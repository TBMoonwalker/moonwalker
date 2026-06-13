<script setup lang="ts">
import { computed, defineAsyncComponent, onMounted, onUnmounted, ref } from 'vue'
import Statistics from '@/components/Statistics.vue'
import { AlertCircleOutline } from '@vicons/ionicons5'
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
const aiTrustRuntimeStatus = computed(() =>
  String(configSnapshotStore.snapshot.value?.ai_trust_runtime_status ?? 'ok')
)
const aiTrustRuntimeProviderStatus = computed(() =>
  String(configSnapshotStore.snapshot.value?.ai_trust_runtime_provider_status ?? '')
)
const aiTrustProviderUnavailable = computed(
  () => aiTrustRuntimeStatus.value === 'provider_unavailable'
)
const aiTrustWarningBlocked = computed(
  () => aiTrustRuntimeStatus.value === 'warning_blocked'
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
  <div class="page-shell trades-page">
    <n-flex class="page-section" vertical>
      <n-card
        class="dashboard-header-card mw-shell-card"
        content-style="padding: 14px 16px;"
      >
        <n-flex class="page-header trades-header" vertical :size="12">
          <div class="header-statistics">
            <Statistics />
          </div>
            <div
              class="trading-pause-strip"
              :class="{
                'trading-pause-strip-active': tradingPaused || tradeAdmissionWarning,
              }"
              aria-live="polite"
            >
              <n-tag
                :type="admissionStatusTagType"
                :bordered="false"
              >
                {{ admissionStatusLabel }}
              </n-tag>
              <span class="trading-pause-copy">
                {{ admissionStatusCopy }}
              </span>
            </div>
        </n-flex>
      </n-card>
    </n-flex>

    <n-flex class="page-section" vertical>
      <n-card class="dashboard-surface-card mw-shell-card" content-style="padding: 0;">
        <n-tabs
          v-model:value="activeProfitTab"
          type="line"
          size="large"
          :tabs-padding="tabPadding"
        >
          <n-tab-pane name="profit-overall" tab="Profit overall">
            <UpnlChart v-if="activeProfitTab === 'profit-overall'" />
          </n-tab-pane>
          <n-tab-pane name="daily-profit" tab="Daily profit">
            <Charts v-if="activeProfitTab === 'daily-profit'" period="daily" />
          </n-tab-pane>
          <n-tab-pane name="monthly-profit" tab="Monthly profit">
            <Charts v-if="activeProfitTab === 'monthly-profit'" period="monthly" />
          </n-tab-pane>
          <n-tab-pane name="yearly-profit" tab="Yearly profit">
            <Charts v-if="activeProfitTab === 'yearly-profit'" period="yearly" />
          </n-tab-pane>
        </n-tabs>
      </n-card>
    </n-flex>

    <n-flex class="page-section" vertical>
      <n-card class="dashboard-surface-card mw-shell-card" content-style="padding: 0;">
        <n-tabs
          v-model:value="activeTradesTab"
          type="line"
          size="large"
          :tabs-padding="tabPadding"
        >
          <n-tab-pane name="open-trades" tab="Open Trades">
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
                <n-icon v-if="unsellableTradesCount > 0" size="16">
                  <AlertCircleOutline />
                </n-icon>
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
      </n-card>
    </n-flex>
  </div>
</template>

<style scoped>
.trades-page {
  gap: 0;
}

.page-section {
  margin-inline: 10px;
  margin-bottom: 10px;
}

.page-section:last-child {
  margin-bottom: 0;
}

.trades-header {
  align-items: stretch;
}

.dashboard-header-card {
  width: 100%;
}

.dashboard-surface-card {
  width: 100%;
}

.header-statistics {
  width: 100%;
}

.trading-pause-strip {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 10px;
  background: rgba(29, 92, 73, 0.05);
}

.trading-pause-strip-active {
  border-color: rgba(183, 138, 46, 0.24);
  background: rgba(183, 138, 46, 0.08);
}

.trading-pause-copy {
  color: var(--mw-color-text-secondary);
  font-size: 0.92rem;
}

.trade-tab-label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.trade-tab-label-warning {
  color: #d97706;
}

.trade-tab-count {
  font-size: 12px;
  font-weight: 600;
}

@media (max-width: 768px) {
  .page-section {
    margin-inline: 6px;
  }

  .trades-header {
    align-items: flex-start;
  }

  .trading-pause-strip {
    width: 100%;
  }
}
</style>
