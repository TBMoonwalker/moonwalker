<script setup lang="ts">
import { computed, h, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import type { DataTableColumns, PaginationProps } from 'naive-ui'
import Heatmap from '../components/Heatmap.vue'
import { useAnalyticsStore } from '../stores/analytics'
import type { AnalyticsOverview } from '../stores/analytics'

const analytics = useAnalyticsStore()
const activeTab = ref('symbols')
const isMobile = ref(false)
const symbolPagination = reactive<PaginationProps>({
   page: 1,
   pageSize: 10,
   pageSlot: 5,
   prefix: ({ itemCount }) => `Total ${itemCount} symbols`,
})

function handleResize() {
   isMobile.value = window.innerWidth < 768
}

onMounted(() => {
   handleResize()
   window.addEventListener('resize', handleResize)
   void analytics.load()
 })

onUnmounted(() => {
   window.removeEventListener('resize', handleResize)
 })

const d = computed(() => analytics.data)
const summary = computed(
      () => (d.value as AnalyticsOverview | null)?.summary ?? null,
 )
const heatmapDaily = computed(
      () => (d.value as AnalyticsOverview | null)?.heatmap_daily ?? [],
 )
const heatmapWeekly = computed(
      () => (d.value as AnalyticsOverview | null)?.heatmap_weekly ?? [],
 )
const perSymbol = computed(
      () => (d.value as AnalyticsOverview | null)?.per_symbol ?? [],
 )
const durationExtremes = computed(
      () => (d.value as AnalyticsOverview | null)?.duration_extremes ?? null,
 )
const drawdown = computed(
      () => (d.value as AnalyticsOverview | null)?.drawdown ?? null,
 )
const distribution = computed(
      () => (d.value as AnalyticsOverview | null)?.distribution ?? null,
 )

const heatmapData = computed(
       () => (d.value as AnalyticsOverview | null)?.heatmap_daily ?? [],
 )

watch(perSymbol, (rows) => {
   const pageSize = symbolPagination.pageSize ?? 10
   const maxPage = Math.max(1, Math.ceil(rows.length / pageSize))
   if ((symbolPagination.page ?? 1) > maxPage) {
     symbolPagination.page = maxPage
   }
})

function fmt2(val: number) {
   return val.toFixed(2)
}

function fmtPct(val: number) {
   return `${val}%`
}

function fmtRangePct(val: number) {
   const normalized = Object.is(val, -0) ? 0 : val
   return `${normalized.toFixed(2)}%`
}

function fmtProfitRange(row: { min: number; max: number }) {
   if (row.min === row.max) {
     return fmtRangePct(row.min)
   }
   return `${fmtRangePct(row.min)} to ${fmtRangePct(row.max)}`
}

const tabNames = [
      { name: 'symbols', label: 'Symbols' },
      { name: 'duration', label: 'Duration' },
      { name: 'risk', label: 'Risk' },
      { name: 'distribution', label: 'Distribution' },
 ]

function getSymbolColumns(): DataTableColumns<AnalyticsOverview['per_symbol'][number]> {
   return [
      {
       title: 'Symbol',
       key: 'symbol',
       width: 120,
       fixed: 'left',
      },
      {
       title: 'Trades',
       key: 'trades',
       width: 80,
       sorter: 'default',
      },
      {
       title: 'Win Rate',
       key: 'win_rate',
       width: 100,
       sorter: 'default',
       render(row: any) {
        return `${row.win_rate}%`
        },
      },
      {
       title: 'Total Profit',
       key: 'total_profit',
       width: 120,
       sorter: 'default',
       render(row: any) {
        const color = row.total_profit >= 0
             ? 'rgb(99, 226, 183)'
             : 'rgb(224, 108, 117)'
       return h('span', { style: { color } }, row.total_profit.toFixed(2))
        },
      },
      {
       title: 'Avg Profit',
       key: 'avg_profit',
       width: 100,
       sorter: 'default',
       render(row: any) {
        const color = row.avg_profit >= 0
             ? 'rgb(99, 226, 183)'
             : 'rgb(224, 108, 117)'
        return h('span', { style: { color } }, row.avg_profit.toFixed(2))
        },
      },
      {
       title: 'Avg Duration',
       key: 'avg_duration_formatted',
       width: 100,
      },
    ]
}

function getDurationColumns(): DataTableColumns<AnalyticsOverview['duration_extremes']['longest'][number]> {
   return [
      {
       title: 'Symbol',
       key: 'symbol',
       width: 120,
      },
      {
       title: 'Duration',
       key: 'duration_formatted',
       width: 100,
      },
      {
       title: 'Profit',
       key: 'profit',
       width: 100,
       render(row: any) {
        const color = row.profit >= 0
             ? 'rgb(99, 226, 183)'
             : 'rgb(224, 108, 117)'
        return h('span', { style: { color } }, row.profit.toFixed(2))
        },
      },
      {
       title: 'Profit %',
       key: 'profit_percent',
       width: 100,
       render(row: any) {
        const color = row.profit_percent >= 0
             ? 'rgb(99, 226, 183)'
             : 'rgb(224, 108, 117)'
        return h('span', { style: { color } }, `${row.profit_percent}%`)
        },
      },
      {
       title: 'Closed',
       key: 'close_date',
       width: 160,
       render(row: any) {
        return row.close_date
             ? new Date(row.close_date).toLocaleDateString()
             : '-'
        },
      },
    ]
}

function getDistributionColumns(): DataTableColumns<{ label: string; min: number; max: number; count: number }> {
   return [
      {
       title: 'Outcome',
       key: 'label',
       width: 120,
      },
      {
       title: 'Range',
       width: 160,
       render(row: any) {
        return fmtProfitRange(row)
        },
      },
      {
       title: 'Trades',
       key: 'count',
       width: 80,
      },
    ]
}
</script>

<template>
   <div class="page-shell stats-page">
      <!-- Empty / error state -->
      <template v-if="!summary">
        <n-flex class="page-section" vertical>
          <n-card class="stats-intro-card mw-shell-card" content-style="padding: 18px 20px;">
            <n-flex vertical :size="6">
              <n-text depth="3" class="stats-kicker">Statistics</n-text>
              <n-text>
                <template v-if="analytics.loading">Loading analytics...</template>
                <template v-else-if="analytics.error">
                   <n-alert type="error" :show-icon="false">
                     {{ analytics.error }}
                     <n-button size="small" strong secondary type="primary" @click="analytics.load">Retry</n-button>
                   </n-alert>
                </template>
                <template v-else>No closed trades yet. Statistics will appear after your first trade closes.</template>
              </n-text>
            </n-flex>
          </n-card>
        </n-flex>
      </template>

      <!-- Main content -->
      <template v-else>
        <!-- KPI Cards -->
        <n-flex class="page-section" vertical>
          <n-card content-style="padding: 0;">
            <div class="statistics-grid">
              <div class="stat-cell">
                <n-statistic label="Total Trades" :value="summary.total_trades" />
              </div>
              <div class="stat-cell">
                <n-statistic label="Win Rate" :value="fmtPct(summary.win_rate)" />
              </div>
              <div class="stat-cell">
                <n-statistic
                    :class="summary.total_profit >= 0 ? 'green' : 'red'"
                  label="Total Profit"
                    :value="fmt2(summary.total_profit)"
                />
              </div>
              <div class="stat-cell">
                <n-statistic
                    :class="summary.avg_profit >= 0 ? 'green' : 'red'"
                  label="Avg Profit"
                    :value="fmt2(summary.avg_profit)"
                />
              </div>
              <div class="stat-cell">
                <n-statistic label="Avg Duration" :value="summary.avg_duration_formatted" />
              </div>
            </div>
          </n-card>
        </n-flex>

        <!-- Heatmap -->
        <n-flex class="page-section" vertical>
          <n-card class="heatmap-card mw-shell-card" content-style="padding: 18px 20px;">
            <n-flex vertical :size="10">
              <n-text depth="3" class="stats-kicker">Trade Activity</n-text>
              <Heatmap :data="heatmapData" />
            </n-flex>
          </n-card>
        </n-flex>

        <!-- Analytics Tabs -->
        <n-flex class="page-section" vertical>
          <n-card content-style="padding: 0;">
            <n-tabs v-model:value="activeTab" type="line" :tabs-padding="isMobile ? 12 : 20">
              <n-tab-pane v-for="tab in tabNames" :key="tab.name" :name="tab.name" :tab="tab.label">
                <div v-show="activeTab === tab.name" class="tab-content">
                  <!-- Symbols Tab -->
                  <template v-if="tab.name === 'symbols' && perSymbol.length">
                    <n-data-table
                        :columns="getSymbolColumns()"
                        :data="perSymbol"
                        :pagination="symbolPagination"
                        :scroll-x="500"
                       size="small"
                    />
                  </template>
                  <n-empty v-else-if="tab.name === 'symbols'" description="No symbol data available" />

                  <!-- Duration Tab -->
                  <template v-if="tab.name === 'duration' && durationExtremes">
                    <n-flex :size="16" class="duration-panel" vertical>
                      <n-flex vertical :size="6">
                        <n-text strong>Longest Trades</n-text>
                        <n-data-table
                            :columns="getDurationColumns()"
                            :data="durationExtremes.longest"
                            :pagination="false"
                            :scroll-x="500"
                           size="small"
                        />
                      </n-flex>
                      <n-flex vertical :size="6">
                        <n-text strong>Shortest Trades</n-text>
                        <n-data-table
                            :columns="getDurationColumns()"
                            :data="durationExtremes.shortest"
                            :pagination="false"
                            :scroll-x="500"
                           size="small"
                        />
                      </n-flex>
                    </n-flex>
                  </template>
                  <n-empty v-else-if="tab.name === 'duration'" description="No duration data available" />

                  <!-- Risk Tab -->
                  <template v-if="tab.name === 'risk' && drawdown">
                    <n-flex :size="12" vertical>
                      <div class="stat-cell risk-stat">
                        <n-statistic
                            class="red"
                            label="Max Drawdown"
                            :value="fmt2(drawdown.max_drawdown)"
                        />
                        <span class="stat-detail">{{ fmtPct(drawdown.max_drawdown_percent) }}</span>
                      </div>
                      <n-card content-style="padding: 12px;">
                        <n-flex vertical :size="4">
                          <n-text depth="3" style="font-size: 12px;">How to read this</n-text>
                          <n-text depth="3" style="font-size: 12px;">
                           Max drawdown measures the worst peak-to-trough loss. Lower is better.
                           If max drawdown is 10 USDT, that means at some point your cumulative
                           profit fell by 10 USDT from its highest point.
                          </n-text>
                        </n-flex>
                      </n-card>
                    </n-flex>
                  </template>

                  <!-- Distribution Tab -->
                  <template v-if="tab.name === 'distribution' && distribution">
                    <n-flex :size="16" vertical>
                      <n-flex :size="8" vertical>
                        <n-text strong>Profit Distribution Breakdown</n-text>
                        <n-data-table
                            :columns="getDistributionColumns()"
                            :data="distribution.bins"
                            :pagination="false"
                            :scroll-x="400"
                           size="small"
                        />
                        <n-flex :size="12" class="distribution-stats">
                          <div v-if="!isMobile" class="stat-cell dist-stat">
                            <n-statistic label="Median" :value="fmtPct(distribution.median)" />
                          </div>
                          <div v-if="!isMobile" class="stat-cell dist-stat">
                            <n-statistic label="Std Dev" :value="fmtPct(distribution.std_dev)" />
                          </div>
                          <div class="stat-cell dist-stat">
                            <n-statistic class="green" label="Best Trade" :value="fmtPct(distribution.best)" />
                          </div>
                          <div class="stat-cell dist-stat">
                            <n-statistic class="red" label="Worst Trade" :value="fmtPct(distribution.worst)" />
                          </div>
                        </n-flex>
                      </n-flex>
                    </n-flex>
                  </template>
                </div>
              </n-tab-pane>
            </n-tabs>
          </n-card>
        </n-flex>
      </template>
    </div>
 </template>

<style scoped>
.stats-page {
  gap: 0;
}

.page-section {
  margin-inline: 10px;
  margin-bottom: 10px;
}

.page-section:last-child {
  margin-bottom: 0;
}

.stats-kicker {
  font-size: 0.82rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.tab-content {
  padding: 12px;
}

/* KPI grid */
.statistics-grid {
  width: 100%;
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 12px;
}

.stat-cell {
  min-width: 0;
  padding: 6px 10px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.02);
  display: flex;
  align-items: center;
  justify-content: center;
}

.stat-detail {
  color: var(--n-text-color-3, #8a948d);
  font-size: 12px;
  line-height: 1.25;
  text-align: center;
  overflow-wrap: anywhere;
}

:deep(.n-statistic) {
  width: 100%;
  text-align: center;
}

:deep(.n-statistic-value) {
  font-variant-numeric: tabular-nums;
}

.red {
   --n-value-text-color: rgb(224, 108, 117) !important;
}

.green {
   --n-value-text-color: rgb(99, 226, 183) !important;
}

.risk-stat {
  flex-direction: column;
  gap: 4px;
}

.heatmap-card {
  width: 100%;
}

.duration-panel {
  padding: 12px;
}

@media (max-width: 768px) {
   .tab-content {
    padding: 8px;
   }

   .page-section {
    margin-inline: 6px;
   }

   :deep(.n-tabs-tab-bar) {
    flex-direction: row;
    overflow-x: auto;
   }

   :deep(.n-tabs-tab) {
    white-space: nowrap;
   }

   .stats-intro-card {
    margin-inline: 6px;
   }

   .distribution-stats {
    flex-wrap: wrap;
   }

   .dist-stat {
    min-width: calc(50% - 6px);
   }

   .statistics-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    overflow: visible;
    gap: 8px;
   }

   .stat-cell {
    min-width: 0;
    min-height: 82px;
    padding: 8px 6px;
    border-radius: 6px;
   }

   :deep(.n-statistic-label) {
    font-size: 12px;
    line-height: 1.2;
   }

   :deep(.n-statistic-value) {
    font-size: 24px;
    line-height: 1.15;
   }

}

@media (min-width: 769px) and (max-width: 1200px) {
   .statistics-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
   }
}
</style>
