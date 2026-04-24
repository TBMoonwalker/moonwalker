<template>
  <div class="chart-wrap">
    <n-spin :show="isLoading" size="small">
      <v-chart
        v-if="!isLoading && !showEmptyState"
        class="chart"
        :option="option"
        :style="{ height: chartHeight }"
        autoresize
      />
      <div v-else class="chart-placeholder chart-empty" :style="{ height: chartHeight }">
        {{ emptyStateText }}
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

use([GridComponent, LegendComponent, TooltipComponent, LineChart, CanvasRenderer])

const upnlStore = useUpnlDatastore()
const { data } = storeToRefs(upnlStore)
const statisticsStore = useWebSocketDataStore('statistics')
const statisticsData = storeToRefs(statisticsStore)

const isLoading = ref(true)
const showEmptyState = ref(false)
const emptyStateText = ref('No profit history yet')
const chartHeight = ref('40vh')

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
  const labels = data.value.map((point) => point.timestamp)
  const profitValues = data.value.map((point) => Number(point.profit_overall))
  const lockedValues = data.value.map((point) => Number(point.funds_locked))
  const latestProfitValue = profitValues.length > 0 ? profitValues[profitValues.length - 1] : 0
  const isNegative = latestProfitValue < 0
  const profitLineColor = isNegative ? 'rgb(224, 108, 117)' : 'rgb(99, 226, 183)'
  const profitAreaColor = isNegative ? 'rgba(224, 108, 117, 0.18)' : 'rgba(99, 226, 183, 0.18)'
  const lockedLineColor = 'rgb(245, 166, 35)'
  const chartTextColor = '#33403A'
  const chartMutedTextColor = '#8A948D'

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
        color: chartTextColor,
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
      splitLine: { show: false },
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
.chart {
  width: 100%;
  max-width: 100%;
}

.chart-wrap {
  width: 100%;
  overflow: hidden;
  padding: 8px 0 16px;
  border-radius: 8px;
}

.chart-placeholder {
  width: 100%;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.04);
}

.chart-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  color: rgba(255, 255, 255, 0.7);
}
</style>
