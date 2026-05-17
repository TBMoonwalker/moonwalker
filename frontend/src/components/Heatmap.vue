<script setup lang="ts">
import { computed } from 'vue'
import type { HeatmapDataItem } from 'naive-ui'

const props = defineProps<{
   data: { timestamp: number; value: number }[]
}>()

const ACTIVE_COLORS = ['#B9D7CB', '#7FB79C', '#4E9272', '#1D5C49']

const heatmapData = computed<HeatmapDataItem[]>(() => {
   return props.data
      .filter((item) => Number.isFinite(item.timestamp))
      .map((item) => ({
         timestamp: item.timestamp,
         value: Math.max(0, item.value),
      }))
      .sort((a, b) => a.timestamp - b.timestamp)
})

function formatTooltip(timestamp: number, value: number | null | undefined): string {
   const date = new Date(timestamp).toLocaleDateString()
   const trades = value ?? 0
   return `${trades} ${trades === 1 ? 'trade' : 'trades'} on ${date}`
}
</script>

<template>
    <div v-if="!heatmapData.length" class="heatmap-empty">
        <n-empty description="No data to display" />
    </div>
    <div v-else class="heatmap-container">
        <n-heatmap
            :data="heatmapData"
            :active-colors="ACTIVE_COLORS"
            minimum-color="rgba(29, 92, 73, 0.12)"
            size="small"
            :x-gap="3"
            :y-gap="3"
            tooltip
        >
            <template #tooltip="{ timestamp, value }">
                {{ formatTooltip(timestamp, value) }}
            </template>
        </n-heatmap>
    </div>
</template>

<style scoped>
.heatmap-empty {
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 120px;
    color: rgba(255, 255, 255, 0.5);
}

.heatmap-container {
    width: 100%;
    overflow-x: auto;
    padding-bottom: 2px;
}

.heatmap-container :deep(.n-heatmap) {
    min-width: fit-content;
}

.heatmap-container :deep(.n-heatmap__calendar-table) {
    font-variant-numeric: tabular-nums;
}
</style>
