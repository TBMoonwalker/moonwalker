<script setup lang="ts">
import { computed, defineAsyncComponent, onMounted, onUnmounted, ref } from 'vue'
import Statistics from '@/components/Statistics.vue'
import WebSocketStatusBar from '@/components/WebSocketStatusBar.vue'
import { ConstructOutline } from '@vicons/ionicons5'
import { useRouter } from 'vue-router'

const OpenTrades = defineAsyncComponent(() => import('../components/OpenTrades.vue'))
const ClosedTrades = defineAsyncComponent(() => import('../components/ClosedTrades.vue'))
const Charts = defineAsyncComponent(() => import('@/components/Charts.vue'))
const UpnlChart = defineAsyncComponent(() => import('@/components/UpnlChart.vue'))

const router = useRouter()
const viewportWidth = ref(window.innerWidth)
const isMobile = computed(() => viewportWidth.value < 768)
const tabPadding = computed(() => (isMobile.value ? 12 : 20))
const activeProfitTab = ref('profit-overall')
const activeTradesTab = ref('open-trades')

function handleResize() {
  viewportWidth.value = window.innerWidth
}

function configureButtonClicked() {
  router.push('/config')
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
      <n-card class="dashboard-header-card" content-style="padding: 14px 16px;">
        <n-flex class="page-header trades-header" vertical :size="12">
          <n-flex class="header-controls" justify="space-between" align="center" :wrap="true" :size="[12, 12]">
            <n-button
              v-if="!isMobile"
              strong
              secondary
              type="primary"
              size="large"
              aria-label="Open configuration"
              title="Open configuration"
              @click="configureButtonClicked"
            >
              <template #icon>
                <n-icon>
                  <ConstructOutline />
                </n-icon>
              </template>
              Configure Bot
            </n-button>
            <n-button
              v-else
              strong
              secondary
              circle
              type="primary"
              size="medium"
              aria-label="Open configuration"
              title="Open configuration"
              @click="configureButtonClicked"
            >
              <template #icon>
                <n-icon>
                  <ConstructOutline />
                </n-icon>
              </template>
            </n-button>
            <div class="stream-status-wrap">
              <WebSocketStatusBar compact />
            </div>
          </n-flex>
          <div class="header-statistics">
            <Statistics />
          </div>
        </n-flex>
      </n-card>
    </n-flex>

    <n-flex class="page-section" vertical>
      <n-card content-style="padding: 0;">
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
      <n-card content-style="padding: 0;">
        <n-tabs
          v-model:value="activeTradesTab"
          size="large"
          :tabs-padding="tabPadding"
        >
          <n-tab-pane name="open-trades" tab="Open Trades">
            <OpenTrades v-if="activeTradesTab === 'open-trades'" />
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

.header-controls {
  width: 100%;
}

.stream-status-wrap {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  flex: 1;
}

.header-statistics {
  width: 100%;
}

@media (max-width: 768px) {
  .page-section {
    margin-inline: 6px;
  }

  .trades-header {
    align-items: flex-start;
  }

  .header-controls {
    align-items: flex-start;
  }

  .stream-status-wrap {
    width: 100%;
    justify-content: flex-start;
  }
}
</style>
