<template>
    <div class="chart-wrap" :style="{ maxWidth: chartWidth }">
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
import { ref, watch } from 'vue'
import { useWebSocketDataStore } from '../stores/websocket'
import { useProfitDatastore } from '../stores/profit'
import { storeToRefs } from 'pinia'
import { use } from 'echarts/core'
import { BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import VChart from 'vue-echarts'
import { NSpin } from 'naive-ui'
const range = defineProps<{ period: string }>()
const profit_store = useProfitDatastore()
const statistics_store = useWebSocketDataStore("statistics")
const statistics_data = storeToRefs(statistics_store)
const chart_data = ref({
    labels: [],
    datasets: [{}]
})
const option = ref({})
const chartHeight = ref('40vh')
const chartWidth = ref('100%')
const isLoading = ref(true)
const showNoProfit = ref(false)
const emptyStateText = ref('')

let historic_data = false
let isLoadingHistory = false

use([GridComponent, TooltipComponent, BarChart, CanvasRenderer])

// Get new statistics data
watch([statistics_data.data, profit_store.data], async ([newData]) => {
    let labels = []
    let datasets = []

    if (!historic_data && !isLoadingHistory) {
        isLoadingHistory = true
        profit_store.data = {}
        await profit_store.load_profit_history_data(range['period'])
        historic_data = true
        isLoadingHistory = false
    }

    if (newData !== undefined && newData !== null) {
        if (profit_store.data && Object.keys(profit_store.data).length > 0) {
            showNoProfit.value = false
            emptyStateText.value = ''
            let profit = profit_store.data
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
            const barWidth = Math.max(12, Math.min(48, Math.floor(480 / count)))
            if (count <= 1) {
                chartHeight.value = '24vh'
                chartWidth.value = '45%'
            } else if (count <= 3) {
                chartHeight.value = '28vh'
                chartWidth.value = '65%'
            } else if (count <= 7) {
                chartHeight.value = '32vh'
                chartWidth.value = '85%'
            } else {
                chartHeight.value = '40vh'
                chartWidth.value = '100%'
            }

            option.value = {
                grid: {
                    show: false,
                    left: 12,
                    right: 8,
                    top: 16,
                    bottom: 24,
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
                    axisLabel: { color: "#fff", margin: 8 },
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
            chartHeight.value = '24vh'
            chartWidth.value = '45%'
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
