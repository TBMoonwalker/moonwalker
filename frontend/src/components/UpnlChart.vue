<template>
  <div class="chart-wrap performance-chart">
    <n-spin :show="isLoading" size="small">
      <v-chart
        v-if="!isLoading && !showEmptyState && visiblePoints.length > 0"
        class="chart"
        :option="option"
        autoresize
      />
      <div v-else class="chart-placeholder chart-empty">
        {{ placeholderText }}
      </div>
    </n-spin>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { use } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import VChart from 'vue-echarts'
import { useUpnlDatastore } from '../stores/upnl'
import { useWebSocketDataStore } from '../stores/websocket'
import { formatTradingViewDate } from '../helpers/date'
import { filterPerformancePoints, type PerformanceRange } from '../helpers/performanceRange'
import { getEffectiveCss } from '../theme/tokens'
import { useThemeStore } from '../theme/themeStore'

use([GridComponent, LegendComponent, TooltipComponent, LineChart, CanvasRenderer])

const props = defineProps<{ range: PerformanceRange }>()
const upnlStore = useUpnlDatastore()
const { data } = storeToRefs(upnlStore)
const statisticsStore = useWebSocketDataStore('statistics')
const statisticsData = storeToRefs(statisticsStore)
const themeStore = useThemeStore()
const { scheme } = storeToRefs(themeStore)

const isLoading = ref(data.value.length === 0)
const showEmptyState = ref(false)
const emptyStateText = ref('No profit history yet')
const visiblePoints = computed(() => filterPerformancePoints(data.value, props.range))
const placeholderText = computed(() =>
  visiblePoints.value.length === 0 && data.value.length > 0
    ? 'No performance data in this range'
    : emptyStateText.value,
)

function toMinuteBucket(timestamp: string): string {
  const date = new Date(timestamp.replace(' ', 'T') + 'Z')
  if (Number.isNaN(date.getTime())) {
    if (timestamp.length >= 16) {
      return timestamp.slice(0, 16)
    }
    return timestamp
  }

  date.setUTCSeconds(0, 0)
  const minute = date.getUTCMinutes()
  date.setUTCMinutes(Math.floor(minute / 15) * 15)

  const year = date.getUTCFullYear()
  const month = String(date.getUTCMonth() + 1).padStart(2, '0')
  const day = String(date.getUTCDate()).padStart(2, '0')
  const hour = String(date.getUTCHours()).padStart(2, '0')
  const min = String(date.getUTCMinutes()).padStart(2, '0')
  return `${year}-${month}-${day} ${hour}:${min}`
}

function pushRealtimePoint(profitOverall: number, fundsLocked: number, timestamp: string): void {
  if (!Number.isFinite(profitOverall) || !Number.isFinite(fundsLocked) || !timestamp) {
    return
  }

  const point = {
    timestamp,
    profit_overall: profitOverall,
    funds_locked: fundsLocked,
  }

  if (data.value.length === 0) {
    data.value = [point]
    return
  }

  const lastIndex = data.value.length - 1
  const lastPoint = data.value[lastIndex]
  if (toMinuteBucket(lastPoint.timestamp) === toMinuteBucket(timestamp)) {
    data.value[lastIndex] = point
  } else {
    data.value.push(point)
  }
}

const option = computed(() => {
  const colors = getEffectiveCss(scheme.value)
  const labels = visiblePoints.value.map((point) => point.timestamp)
  const profitValues = visiblePoints.value.map((point) => Number(point.profit_overall))
  const lockedValues = visiblePoints.value.map((point) => Number(point.funds_locked))
  const latestProfitValue = profitValues.length > 0 ? profitValues[profitValues.length - 1] : 0
  const isNegative = latestProfitValue < 0
  const profitLineColor = isNegative
    ? colors['--mw-color-error']
    : colors['--mw-color-primary']
  const profitAreaColor = isNegative
    ? 'rgba(180, 68, 63, 0.13)'
    : scheme.value === 'dark'
      ? 'rgba(156, 219, 115, 0.12)'
      : 'rgba(39, 107, 71, 0.1)'
  const lockedLineColor = colors['--mw-color-warning']
  const chartLegendTextColor = colors['--mw-color-text-secondary']
  const chartMutedTextColor = colors['--mw-color-text-muted']

  return {
    grid: {
      show: false,
      left: 12,
      right: 8,
      top: 44,
      bottom: 24,
      containLabel: true,
    },
    legend: {
      top: 8,
      right: 8,
      textStyle: {
        color: chartLegendTextColor,
      },
      data: ['Profit overall', 'Funds locked'],
    },
    tooltip: {
      trigger: 'axis',
      axisPointer: {
        type: 'line',
      },
    },
    xAxis: {
      type: 'category',
      data: labels,
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: {
        color: chartMutedTextColor,
        hideOverlap: true,
        formatter: (value: string) => formatTradingViewDate(value),
      },
      boundaryGap: false,
    },
    yAxis: {
      type: 'value',
      axisLabel: { color: chartMutedTextColor },
      splitLine: {
        show: true,
        lineStyle: { color: colors['--mw-color-border'], width: 1 },
      },
    },
    series: [
      {
        name: 'Profit overall',
        data: profitValues,
        type: 'line',
        smooth: 0.35,
        symbol: 'none',
        lineStyle: {
          width: 2,
          color: profitLineColor,
        },
        areaStyle: {
          color: profitAreaColor,
        },
        itemStyle: {
          color: profitLineColor,
        },
      },
      {
        name: 'Funds locked',
        data: lockedValues,
        type: 'line',
        smooth: 0.35,
        symbol: 'none',
        lineStyle: {
          width: 2,
          type: 'dotted',
          color: lockedLineColor,
        },
        itemStyle: {
          color: lockedLineColor,
        },
      },
    ],
  }
})

onMounted(async () => {
  try {
    await upnlStore.load_upnl_history_data()
    showEmptyState.value = data.value.length === 0
  } catch {
    showEmptyState.value = data.value.length === 0
    emptyStateText.value = 'No profit history yet'
  } finally {
    isLoading.value = false
  }
})

watch(
  statisticsData.data,
  (newData) => {
    if (!newData || typeof newData !== 'object') {
      return
    }
    const websocketData = newData as {
      profit_overall?: number
      funds_locked?: number
      profit_overall_timestamp?: string
    }
    if (
      websocketData.profit_overall === undefined ||
      websocketData.funds_locked === undefined ||
      !websocketData.profit_overall_timestamp
    ) {
      return
    }

    pushRealtimePoint(
      Number(websocketData.profit_overall),
      Number(websocketData.funds_locked),
      websocketData.profit_overall_timestamp,
    )
    showEmptyState.value = data.value.length === 0
  },
  { immediate: true },
)
</script>

<style scoped>
.chart-placeholder {
  background: rgba(255, 255, 255, 0.04);
}
</style>
