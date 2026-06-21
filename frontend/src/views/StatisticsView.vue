<script setup lang="ts">
import {
   computed,
   h,
   onActivated,
   onMounted,
   onUnmounted,
   reactive,
   ref,
   watch,
} from 'vue'
import type { DataTableColumns, PaginationProps, SorterResult } from 'naive-ui'
import Heatmap from '../components/Heatmap.vue'
import { useAnalyticsStore } from '../stores/analytics'
import type { AiTrustPrediction, AnalyticsOverview } from '../stores/analytics'

const analytics = useAnalyticsStore()
const activeTab = ref('symbols')
const isMobile = ref(false)
const SYMBOL_PAGE_SIZE = 10
const symbolSortState = ref<{ columnKey: string; order: 'ascend' | 'descend' } | null>({
   columnKey: 'trades',
   order: 'descend',
})
const symbolPagination = reactive<PaginationProps>({
   page: 1,
   pageSize: SYMBOL_PAGE_SIZE,
   pageSlot: 5,
   prefix: ({ itemCount }) => `Total ${itemCount} symbols`,
})
const recentPredictionsPagination = reactive<PaginationProps>({
   page: 1,
   pageSize: SYMBOL_PAGE_SIZE,
   pageSlot: 5,
   prefix: ({ itemCount }) => `Total ${itemCount} predictions`,
})
const badEntryReviewPagination = reactive<PaginationProps>({
   page: 1,
   pageSize: SYMBOL_PAGE_SIZE,
   pageSlot: 5,
   prefix: ({ itemCount }) => `Total ${itemCount} reviews`,
})

function handleSymbolPageChange(page: number) {
   symbolPagination.page = page
}

function handleRecentPredictionsPageChange(page: number) {
   recentPredictionsPagination.page = page
}

function handleBadEntryReviewPageChange(page: number) {
   badEntryReviewPagination.page = page
}

function handleSymbolSorterChange(sorter: SorterResult | null) {
   if (sorter && sorter.order !== false) {
      symbolSortState.value = {
         columnKey: sorter.columnKey ?? sorter.key,
         order: sorter.order as 'ascend' | 'descend',
      }
   } else {
      symbolSortState.value = null
   }
   symbolPagination.page = 1
}

function columnSortOrder(key: string): string | null {
   return symbolSortState.value?.columnKey === key
     ? symbolSortState.value.order
     : null
}

function handleResize() {
   isMobile.value = window.innerWidth < 768
}

onMounted(() => {
   handleResize()
   window.addEventListener('resize', handleResize)
 })

onActivated(() => {
   void analytics.load()
})

onUnmounted(() => {
   window.removeEventListener('resize', handleResize)
 })

const d = computed(() => analytics.data)
const summary = computed(
      () => (d.value as AnalyticsOverview | null)?.summary ?? null,
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
const aiTrust = computed(
      () => (d.value as AnalyticsOverview | null)?.ai_trust ?? null,
 )
const recentPredictions = computed(() => aiTrust.value?.recent_predictions ?? [])
const badEntryReview = computed(() => aiTrust.value?.bad_entry_review ?? [])

const sortedAndPaginatedSymbols = computed(() => {
   let rows = [...perSymbol.value]
   const ss = symbolSortState.value
   if (ss) {
      rows.sort((a: any, b: any) => {
         let aVal = a[ss.columnKey]
         let bVal = b[ss.columnKey]
         if (typeof aVal === 'string') aVal = aVal.toLowerCase()
         if (typeof bVal === 'string') bVal = bVal.toLowerCase()
         if (aVal < bVal) return ss.order === 'ascend' ? -1 : 1
         if (aVal > bVal) return ss.order === 'ascend' ? 1 : -1
         return 0
      })
   }
   const start = ((symbolPagination.page ?? 1) - 1) * (symbolPagination.pageSize ?? SYMBOL_PAGE_SIZE)
   return rows.slice(start, start + (symbolPagination.pageSize ?? SYMBOL_PAGE_SIZE))
})

const heatmapData = computed(
       () => (d.value as AnalyticsOverview | null)?.heatmap_daily ?? [],
 )
const heatmapSummary = computed(() => {
   const rows = heatmapData.value
   const activeDays = rows.filter((row) => Number(row.value ?? 0) > 0).length
   const closedTrades = rows.reduce(
      (total, row) => total + Number(row.value ?? 0),
      0,
   )
   if (!closedTrades) {
     return 'No closed trades in this range'
   }
   const dayLabel = activeDays === 1 ? 'active day' : 'active days'
   return `${closedTrades} closes across ${activeDays} ${dayLabel}`
})
const heatmapMetrics = computed(() => {
   const rows = heatmapData.value
   const activeRows = rows.filter((row) => Number(row.value ?? 0) > 0)
   const closedTrades = activeRows.reduce(
      (total, row) => total + Number(row.value ?? 0),
      0,
   )
   const peak = activeRows.reduce(
      (best, row) =>
         Number(row.value ?? 0) > Number(best?.value ?? 0) ? row : best,
      activeRows[0] ?? null,
   )
   return {
      closedTrades,
      activeDays: activeRows.length,
      peakCount: Number(peak?.value ?? 0),
      peakDate: peak ? new Date(peak.timestamp).toLocaleDateString() : '-',
   }
})

function syncPaginationBounds(pagination: PaginationProps, itemCount: number) {
   const pageSize = pagination.pageSize ?? SYMBOL_PAGE_SIZE
   pagination.itemCount = itemCount
   const maxPage = Math.max(1, Math.ceil(itemCount / pageSize))
   if ((pagination.page ?? 1) > maxPage) {
     pagination.page = maxPage
   }
}

watch(perSymbol, (rows) => {
   const pageSize = symbolPagination.pageSize ?? SYMBOL_PAGE_SIZE
   symbolPagination.itemCount = rows.length
   const maxPage = Math.max(1, Math.ceil(rows.length / pageSize))
   if ((symbolPagination.page ?? 1) > maxPage) {
     symbolPagination.page = maxPage
   }
})

watch(
   recentPredictions,
   (rows) => syncPaginationBounds(recentPredictionsPagination, rows.length),
   { immediate: true },
)

watch(
   badEntryReview,
   (rows) => syncPaginationBounds(badEntryReviewPagination, rows.length),
   { immediate: true },
)

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

function fmtTrustRate(value: number | null | undefined) {
   return `${Number(value ?? 0).toFixed(1)}%`
}

function fmtConfidence(value: number | null) {
   if (value === null) {
     return '-'
   }
   return `${Math.round(value * 100)}%`
}

function fmtTrustDate(value: string | null) {
   return value ? new Date(value).toLocaleString() : '-'
}

const aiTrustStatusText = computed(() => {
   const trust = aiTrust.value
   if (!trust || trust.status === 'disabled') {
     return 'AI observed is disabled'
   }
   if (trust.status === 'missing_model') {
     return 'AI observed is waiting for an Ollama model'
   }
   if (!trust.coverage.total) {
     return 'AI observed is waiting for entry observations'
   }
   const suffix = trust.enforce_warnings
     ? ' · warning entries are blocked'
     : ''
   return `${trust.coverage.scored} scored of ${trust.coverage.total} observations${suffix}`
})

const aiTrustUnscoredCount = computed(() => (
   aiTrust.value?.coverage.unscored ?? 0
))

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
       sortOrder: columnSortOrder('trades'),
      },
      {
       title: 'Win Rate',
       key: 'win_rate',
       width: 100,
       sorter: 'default',
       sortOrder: columnSortOrder('win_rate'),
       render(row: any) {
        return `${row.win_rate}%`
        },
      },
      {
       title: 'Total Profit',
       key: 'total_profit',
       width: 120,
       sorter: 'default',
       sortOrder: columnSortOrder('total_profit'),
       render(row: any) {
        const color = row.total_profit >= 0
              ? '#2E7D5B'
              : '#B4443F'
        return h('span', { style: { color } }, row.total_profit.toFixed(2))
        },
      },
      {
       title: 'Avg Profit',
       key: 'avg_profit',
       width: 100,
       sorter: 'default',
       sortOrder: columnSortOrder('avg_profit'),
        render(row: any) {
         const color = row.avg_profit >= 0
               ? '#2E7D5B'
               : '#B4443F'
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
               ? '#2E7D5B'
               : '#B4443F'
         return h('span', { style: { color } }, row.profit.toFixed(2))
          },
      },
      {
       title: 'Profit %',
       key: 'profit_percent',
       width: 100,
        render(row: any) {
         const color = row.profit_percent >= 0
               ? '#2E7D5B'
               : '#B4443F'
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

function getAiTrustColumns(): DataTableColumns<AiTrustPrediction> {
   return [
      {
       title: 'Symbol',
       key: 'symbol',
       width: 130,
       fixed: 'left',
        render(row) {
         return h('span', { class: 'ai-trust-symbol' }, row.symbol)
        },
      },
      {
       title: 'Observed',
       key: 'created_at',
       width: 160,
        render(row) {
         return fmtTrustDate(row.created_at)
        },
      },
      {
       title: 'Risk',
       key: 'risk_score',
       width: 86,
        render(row) {
         return row.risk_score === null ? '-' : `${row.risk_score}`
        },
      },
      {
       title: 'Confidence',
       key: 'confidence',
       width: 110,
        render(row) {
         return fmtConfidence(row.confidence)
        },
      },
      {
       title: 'AI would have warned',
       key: 'would_warn',
       width: 150,
        render(row) {
         if (row.would_warn === null) {
           return 'Unscored'
         }
         return row.would_warn ? row.warning_severity : 'No'
        },
      },
      {
       title: 'Reasons',
       key: 'reason_codes',
       width: 220,
        render(row) {
         return row.reason_codes.length ? row.reason_codes.join(', ') : row.provider_status
        },
      },
      {
       title: 'Outcome',
       key: 'outcome_status',
       width: 150,
        render(row) {
         if (row.outcome_status === 'blocked') {
           return 'Blocked'
         }
         if (row.outcome_status === 'preflight') {
           return 'Preflight'
         }
         if (row.outcome_status !== 'closed') {
           return 'Open'
         }
         return row.bad_entry ? 'Bad entry' : 'Closed ok'
        },
      },
   ]
}
</script>

<template>
   <div class="page-shell stats-page operator-console-page">
      <!-- Empty / error state -->
      <template v-if="!summary">
        <n-flex class="page-section" vertical>
          <n-card class="dashboard-panel ledger-panel" content-style="padding: 18px 20px;">
            <n-flex vertical :size="6">
              <n-text>
                <template v-if="analytics.loading">Loading analytics…</template>
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
          <div class="statistics-grid" aria-label="Statistics overview">
            <div class="stat-cell dashboard-panel">
              <n-statistic label="Total Trades" :value="summary.total_trades" />
            </div>
            <div class="stat-cell dashboard-panel">
              <n-statistic label="Win Rate" :value="fmtPct(summary.win_rate)" />
            </div>
            <div class="stat-cell dashboard-panel">
              <n-statistic
                  :class="summary.total_profit >= 0 ? 'green' : 'red'"
                label="Total Profit"
                  :value="fmt2(summary.total_profit)"
              />
            </div>
            <div class="stat-cell dashboard-panel">
              <n-statistic
                  :class="summary.avg_profit >= 0 ? 'green' : 'red'"
                label="Avg Profit"
                  :value="fmt2(summary.avg_profit)"
              />
            </div>
            <div class="stat-cell dashboard-panel">
              <n-statistic label="Avg Duration" :value="summary.avg_duration_formatted" />
            </div>
          </div>
        </n-flex>

        <!-- Heatmap -->
        <n-flex class="page-section" vertical>
          <n-card class="heatmap-card dashboard-panel" content-style="padding: 12px 16px;">
            <n-flex vertical :size="6">
              <div class="heatmap-header">
                <n-text depth="3" class="stats-kicker">Trade Activity</n-text>
                <span class="heatmap-summary">{{ heatmapSummary }}</span>
              </div>
              <div class="heatmap-body">
                <Heatmap :data="heatmapData" />
                <dl class="heatmap-metrics" aria-label="Trade activity summary">
                  <div>
                    <dt>Closes</dt>
                    <dd>{{ heatmapMetrics.closedTrades }}</dd>
                  </div>
                  <div>
                    <dt>Active days</dt>
                    <dd>{{ heatmapMetrics.activeDays }}</dd>
                  </div>
                  <div>
                    <dt>Peak day</dt>
                    <dd>{{ heatmapMetrics.peakCount }} · {{ heatmapMetrics.peakDate }}</dd>
                  </div>
                </dl>
              </div>
            </n-flex>
          </n-card>
        </n-flex>

        <!-- AI Trust Cockpit -->
        <n-flex class="page-section" vertical>
          <n-card class="ai-trust-card dashboard-panel ledger-panel" content-style="padding: 14px 16px;">
            <n-flex vertical :size="12">
              <div class="ai-trust-header">
                <div>
                  <n-text depth="3" class="stats-kicker">AI Trust Cockpit</n-text>
                  <div class="ai-trust-status">{{ aiTrustStatusText }}</div>
                </div>
                <n-tag
                    size="small"
                    :type="aiTrust?.status === 'ready' ? 'success' : aiTrust?.status === 'missing_model' ? 'warning' : 'default'"
                >
                  {{ aiTrust?.provider ?? 'ollama' }}
                </n-tag>
              </div>

              <div class="ai-trust-grid" aria-label="AI trust calibration">
                <div class="stat-cell ai-trust-stat">
                  <n-statistic
                      label="Coverage"
                      :value="fmtTrustRate(aiTrust?.coverage.coverage_rate)"
                  />
                  <span class="stat-detail">{{ aiTrust?.coverage.scored ?? 0 }} scored</span>
                </div>
                <div class="stat-cell ai-trust-stat">
                  <n-statistic
                      label="Bad-entry capture"
                      :value="fmtTrustRate(aiTrust?.quality.bad_entry_capture_rate)"
                  />
                  <span class="stat-detail">{{ aiTrust?.quality.bad_entries ?? 0 }} bad entries</span>
                </div>
                <div class="stat-cell ai-trust-stat">
                  <n-statistic
                      label="False warnings"
                      :value="fmtTrustRate(aiTrust?.quality.false_warning_rate)"
                  />
                  <span class="stat-detail">{{ aiTrust?.quality.warnings ?? 0 }} warnings</span>
                </div>
                <div class="stat-cell ai-trust-stat">
                  <n-statistic label="Unscored" :value="aiTrustUnscoredCount" />
                  <span class="stat-detail">{{ aiTrust?.status ?? 'disabled' }}</span>
                </div>
              </div>

              <n-alert
                  v-if="aiTrust?.status === 'disabled'"
                  type="default"
                  :show-icon="false"
              >
                AI observed is off. No entry observations are being recorded.
              </n-alert>
              <n-alert
                  v-else-if="aiTrust?.status === 'missing_model'"
                  type="warning"
                  :show-icon="false"
              >
                AI observed is enabled, but no Ollama model is configured.
              </n-alert>

              <n-flex :size="12" class="ai-trust-tables" vertical>
                <n-flex vertical :size="6">
                  <n-text strong>Recent Predictions</n-text>
                  <n-data-table
                      v-if="recentPredictions.length"
                      :columns="getAiTrustColumns()"
                      :data="recentPredictions"
                      :pagination="recentPredictionsPagination"
                      :scroll-x="1000"
                      size="small"
                      @update:page="handleRecentPredictionsPageChange"
                  />
                  <n-empty
                      v-else
                      description="No AI observed entries yet"
                  />
                </n-flex>
                <n-flex vertical :size="6">
                  <n-text strong>Bad-entry Review</n-text>
                  <n-data-table
                      v-if="badEntryReview.length"
                      :columns="getAiTrustColumns()"
                      :data="badEntryReview"
                      :pagination="badEntryReviewPagination"
                      :scroll-x="1000"
                      size="small"
                      @update:page="handleBadEntryReviewPageChange"
                  />
                  <n-empty
                      v-else
                      description="No calibrated bad-entry review yet"
                  />
                </n-flex>
              </n-flex>
            </n-flex>
          </n-card>
        </n-flex>

        <!-- Analytics Tabs -->
        <n-flex class="page-section" vertical>
          <n-card class="dashboard-panel ledger-panel" content-style="padding: 0;">
            <n-tabs
                v-model:value="activeTab"
                class="calm-tabs statistics-tabs"
                type="line"
                size="large"
                :tabs-padding="isMobile ? 12 : 20"
            >
              <n-tab-pane v-for="tab in tabNames" :key="tab.name" :name="tab.name" :tab="tab.label">
                <div v-show="activeTab === tab.name" class="tab-content">
                  <!-- Symbols Tab -->
                    <template v-if="tab.name === 'symbols' && perSymbol.length">
                      <n-data-table
                         remote
                         :columns="getSymbolColumns()"
                         :data="sortedAndPaginatedSymbols"
                         :pagination="symbolPagination"
                         :scroll-x="500"
                         size="small"
                         @update:page="handleSymbolPageChange"
                         @update:sorter="handleSymbolSorterChange"
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
                      <div class="risk-note operator-subpanel">
                        <n-flex vertical :size="4">
                          <n-text depth="3" style="font-size: 12px;">How to read this</n-text>
                          <n-text depth="3" style="font-size: 12px;">
                           Max drawdown measures the worst peak-to-trough loss. Lower is better.
                           If max drawdown is 10 USDT, that means at some point your cumulative
                           profit fell by 10 USDT from its highest point.
                          </n-text>
                        </n-flex>
                      </div>
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
  gap: 12px;
}

.page-section {
  min-width: 0;
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
  padding: 0;
}

/* KPI grid */
.statistics-grid {
  width: 100%;
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 12px;
}

.stat-cell {
  min-height: 112px;
  min-width: 0;
  padding: 14px 16px;
  display: flex;
  align-items: flex-start;
  justify-content: flex-start;
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
  text-align: left;
}

:deep(.n-statistic-value) {
  font-variant-numeric: tabular-nums;
}

.red {
    --n-value-text-color: #B4443F !important;
}

.green {
    --n-value-text-color: #2E7D5B !important;
}

.risk-stat {
  flex-direction: column;
  gap: 4px;
}

.risk-note {
  padding: 12px;
}

.heatmap-card {
  width: 100%;
}

.heatmap-header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px 16px;
  flex-wrap: wrap;
}

.heatmap-summary {
  color: var(--mw-color-text-secondary);
  font-size: 0.82rem;
  font-variant-numeric: tabular-nums;
  line-height: 1.25;
}

.heatmap-body {
  display: grid;
  grid-template-columns: minmax(220px, max-content) minmax(220px, 1fr);
  align-items: start;
  gap: 16px;
}

.heatmap-metrics {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  margin: 0;
}

.heatmap-metrics div {
  min-width: 0;
  padding: 8px 10px;
  border: 1px solid var(--mw-color-border);
  border-radius: var(--mw-radius-sm, 6px);
  background: rgba(29, 92, 73, 0.05);
}

.heatmap-metrics dt {
  color: var(--mw-color-text-secondary);
  font-size: 0.75rem;
  line-height: 1.2;
}

.heatmap-metrics dd {
  margin: 3px 0 0;
  color: var(--mw-color-text-primary);
  font-size: 0.95rem;
  font-variant-numeric: tabular-nums;
  font-weight: 500;
  line-height: 1.25;
  overflow-wrap: anywhere;
}

.ai-trust-card {
  width: 100%;
}

.ai-trust-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.ai-trust-status {
  color: var(--mw-color-text-primary);
  font-size: 1rem;
  font-weight: 500;
  line-height: 1.25;
  margin-top: 2px;
  overflow-wrap: anywhere;
}

.ai-trust-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.ai-trust-stat {
  flex-direction: column;
  gap: 4px;
  min-height: 82px;
}

.ai-trust-symbol {
  display: inline-block;
  max-width: 100%;
  overflow-wrap: anywhere;
}

:deep(.ai-trust-card .n-data-table-td) {
  white-space: normal;
  overflow-wrap: anywhere;
}

.duration-panel {
  padding: 12px;
}

@media (max-width: 768px) {
   .tab-content {
    padding: 0;
   }

   .page-section {
    min-width: 0;
   }

   :deep(.n-tabs-tab-bar) {
    flex-direction: row;
    overflow-x: auto;
   }

   :deep(.n-tabs-tab) {
    white-space: nowrap;
   }

   .distribution-stats {
    flex-wrap: wrap;
   }

   .heatmap-body {
    grid-template-columns: 1fr;
   }

   .heatmap-metrics {
    grid-template-columns: repeat(3, minmax(0, 1fr));
   }

   .ai-trust-header {
    align-items: stretch;
    flex-direction: column;
   }

   .ai-trust-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
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
    grid-template-columns: repeat(2, minmax(0, 1fr));
    }

    .ai-trust-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    }
}
</style>
