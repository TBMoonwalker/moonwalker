<template>
    <v-chart class="chart" :option="option" autoresize />
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
const range = defineProps<{ period: string }>()
const profit_store = useProfitDatastore()
const statistics_store = useWebSocketDataStore("statistics")
const statistics_data = storeToRefs(statistics_store)
const chart_data = ref()
chart_data.value = {
    labels: [],
    datasets: [{}]
}
const option = ref({})

let historic_data = false

use([GridComponent, TooltipComponent, BarChart, CanvasRenderer])

// Get new statistics data
watch(statistics_data.json, async (newData) => {
    let labels = []
    let datasets = []

    if (!historic_data) {
        profit_store.data = {}
        profit_store.load_profit_history_data(range['period'])
    }

    historic_data = true

    if (newData !== undefined) {
        if (profit_store.data) {
            console.log(profit_store.data)
            let profit = profit_store.data
            for (let key in profit) {
                let value = profit[key]
                labels.push(key)
                datasets.push(chart_classes(value))
            }

            if (range['period'] == "daily") {
                let websocket_data = JSON.parse(newData)
                let profit_week: number = websocket_data["profit_week"]
                let actual_day_value = Number(Object.values(profit_week)[Object.values(profit_week).length - 1])
                datasets.splice(datasets.length - 1, 1, chart_classes(actual_day_value))
            }

            chart_data.value = {
                labels: labels,
                datasets: datasets
            }


            option.value = {
                grid: { show: false },
                tooltip: {
                    trigger: "axis",
                    axisPointer: {
                        type: "shadow"
                    }
                },
                xAxis: {
                    axisLine: { show: false },
                    axisTick: { show: false },
                    axisLabel: { color: "#fff" },
                    type: 'category',
                    data: chart_data.value.labels
                },
                yAxis: {
                    axisLabel: { color: "#fff" },
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
                        itemStyle: { borderRadius: 4 }
                    }
                ]
            }
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
    height: 40vh;
    max-width: 100%;
    margin-top: -50px;
    margin-bottom: -30px;
}
</style>
