<template>
    <div class="chart-wrap">
        <n-spin :show="isLoading" size="small">
            <v-chart v-if="!isLoading && !showNoProfit" class="chart" :option="option" :style="{ height: chartHeight }"
                autoresize />
            <div v-else class="chart-placeholder chart-empty" :style="{ height: chartHeight }">
                {{ emptyStateText }}
            </div>
        </n-spin>
    </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useWebSocketDataStore } from '../stores/websocket'
import { useProfitDatastore } from '../stores/profit'
import { storeToRefs } from 'pinia'
import { use } from 'echarts/core'
import { BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import VChart from 'vue-echarts'
import { formatTradingViewDate } from '../helpers/date'
const range = defineProps<{ period: string }>()
const profit_store = useProfitDatastore()
const statistics_store = useWebSocketDataStore("statistics")
const statistics_data = storeToRefs(statistics_store)
const profit_store_refs = storeToRefs(profit_store)
const chart_data = ref({
    labels: [],
    datasets: [{}]
})
const option = ref({})
const chartHeight = ref('40vh')
const isLoading = ref(true)
const showNoProfit = ref(false)
const emptyStateText = ref('')
const isMobile = ref(false)

let historic_data = false
let isLoadingHistory = false

use([GridComponent, TooltipComponent, BarChart, CanvasRenderer])

function getIsMobileViewport(): boolean {
    if (typeof window === 'undefined') {
        return false
    }
    return window.matchMedia('(max-width: 768px)').matches
}

function handleResize(): void {
    isMobile.value = getIsMobileViewport()
}

onMounted(() => {
    handleResize()
    if (typeof window !== 'undefined') {
        window.addEventListener('resize', handleResize)
    }
})

onBeforeUnmount(() => {
    if (typeof window !== 'undefined') {
        window.removeEventListener('resize', handleResize)
    }
})

// Get new statistics data
watch([statistics_data.data, profit_store_refs.data], async ([newData]) => {
    let labels = []
    let datasets = []

    const hasHistoricProfitData =
        !!profit_store_refs.data.value && Object.keys(profit_store_refs.data.value).length > 0
    const websocketData = newData as any
    const profitWeekCount =
        websocketData && websocketData.profit_week
            ? Object.keys(websocketData.profit_week).length
            : 0
    const shouldRefreshHistory =
        !isLoadingHistory &&
        (!historic_data || (!hasHistoricProfitData && profitWeekCount > 0))

    if (shouldRefreshHistory) {
        isLoadingHistory = true
        profit_store.$patch({ data: {} })
        await profit_store.load_profit_history_data(range['period'])
        historic_data = true
        isLoadingHistory = false
    }

    if (newData !== undefined && newData !== null) {
        if (profit_store_refs.data.value && Object.keys(profit_store_refs.data.value).length > 0) {
            showNoProfit.value = false
            emptyStateText.value = ''
            const profit = profit_store_refs.data.value as Record<string, number>
            for (let key in profit) {
                let value = profit[key]
                labels.push(key)
                datasets.push(chart_classes(value))
            }

            if (range['period'] == "daily") {
                let websocket_data = newData as any
                let profit_week: number = websocket_data["profit_week"]
                let actual_day_value = Number(Object.values(profit_week)[Object.values(profit_week).length - 1])
                datasets.splice(datasets.length - 1, 1, chart_classes(actual_day_value))
            }

            chart_data.value = {
                labels: labels,
                datasets: datasets
            }

            const count = chart_data.value.labels.length || 1
            const maxBarWidth = isMobile.value ? 24 : 48
            const minBarWidth = isMobile.value ? 8 : 12
            const barWidth = Math.max(minBarWidth, Math.min(maxBarWidth, Math.floor(480 / count)))
            if (count <= 1) {
                chartHeight.value = isMobile.value ? '26vh' : '24vh'
            } else if (count <= 3) {
                chartHeight.value = isMobile.value ? '30vh' : '28vh'
            } else if (count <= 7) {
                chartHeight.value = isMobile.value ? '34vh' : '32vh'
            } else {
                chartHeight.value = isMobile.value ? '36vh' : '40vh'
            }

            option.value = {
                grid: {
                    show: false,
                    left: isMobile.value ? 4 : 12,
                    right: isMobile.value ? 4 : 8,
                    top: 16,
                    bottom: isMobile.value ? 36 : 24,
                    containLabel: true
                },
                tooltip: {
                    trigger: "axis",
                    axisPointer: {
                        type: "shadow"
                    }
                },
                xAxis: {
                    axisLine: { show: false },
                    axisTick: { show: false },
                    axisLabel: {
                        color: "#fff",
                        margin: 8,
                        hideOverlap: true,
                        formatter: (value: string) => formatTradingViewDate(value),
                    },
                    type: 'category',
                    data: chart_data.value.labels,
                    boundaryGap: true
                },
                yAxis: {
                    axisLabel: { color: "#fff", margin: 8 },
                    splitLine: {
                        show: false
                    },
                    type: 'value'
                },
                series: [
                    {
                        color: 'rgb(99, 226, 183)',
                        data: chart_data.value.datasets,
                        type: 'bar',
                        barWidth,
                        barMaxWidth: 48,
                        itemStyle: { borderRadius: 4 }
                    }
                ]
            }
            isLoading.value = false
        } else {
            showNoProfit.value = true
            emptyStateText.value = 'No profit yet'
            chartHeight.value = isMobile.value ? '26vh' : '24vh'
            isLoading.value = false
        }
    }

}, { immediate: true })

function chart_classes(data: any) {
    let column_color = 'rgb(99, 226, 183)'
    if (Math.sign(data) <= 0) {
        column_color = 'rgb(224, 108, 117)'
    }
    return {
        value: data,
        itemStyle: {
            color: column_color
        }
    }
}

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
