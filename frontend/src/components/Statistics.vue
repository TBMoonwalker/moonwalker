<template>
    <n-statistic :class="profit_class" label="Profit overall" :value="profit_overall" />
    <n-statistic :class="upnl_class" label="UPNL" :value="upnl" />
    <n-statistic label="Autopilot mode" :value="autopilot_mode" />
    <n-statistic label="Funds locked" :value="funds_locked" />
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { useWebSocketDataStore } from '../stores/websocket'
import { storeToRefs } from 'pinia'

const statistics_store = useWebSocketDataStore("statistics")
const statistics_data = storeToRefs(statistics_store)
const profit_overall = ref()
const profit_class = ref()
const upnl = ref()
const upnl_class = ref()
const funds_locked = ref()
const autopilot_mode = ref()
autopilot_mode.value = "Medium"

// Get new statistics data
watch(statistics_data.json, async (newData) => {
    if (newData !== undefined) {
        const websocket_data = JSON.parse(newData)
        upnl.value = websocket_data.upnl.toFixed(2)
        upnl_class.value = row_classes(upnl.value)
        profit_overall.value = websocket_data.profit_overall.toFixed(2)
        profit_class.value = row_classes(profit_overall.value)
        funds_locked.value = websocket_data.funds_locked.toFixed(2)
    }

}, { immediate: true })

function row_classes(data: any) {
    if (Math.sign(data) >= 0) {
        return 'green'
    } else {
        return 'red'
    }
}

</script>

<style scoped>
.red {
    --n-value-text-color: rgb(224, 108, 117) !important;
}

.green {
    --n-value-text-color: rgb(99, 226, 183) !important;
}
</style>
