<script setup lang="ts">
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import type { HeatmapDataItem } from 'naive-ui'
import { normalizeTradeHeatmapData } from '../helpers/heatmap'
import { useThemeStore } from '../theme/themeStore'
import type { ColorScheme } from '../theme/tokens'

const props = defineProps<{
   data: { timestamp: number; value: number }[]
}>()

const ACTIVE_COLORS = ['#B9D7CB', '#7FB79C', '#4E9272', '#1D5C49']

const heatmapData = computed<HeatmapDataItem[]>(() => {
   return normalizeTradeHeatmapData(props.data)
})

// The empty-cell wash follows the scheme's brand green so it blends with the
// active surface. Light brand green is #1d5c49 (rgb 29, 92, 73); dark is
// #245f4e (rgb 36, 95, 78) -- the per-scheme --mw-color-primary in tokens.ts.
// Naive UI resolves this string verbatim as each empty cell's background, so a
// per-scheme JS value (not a CSS var) is required to retheme the canvas wash.
const MINIMUM_COLOR_BY_SCHEME: Record<ColorScheme, string> = {
  light: 'rgba(29, 92, 73, 0.12)',
  dark: 'rgba(36, 95, 78, 0.12)',
}

const { scheme } = storeToRefs(useThemeStore())

const minimumColor = computed(() => MINIMUM_COLOR_BY_SCHEME[scheme.value])

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
             :minimum-color="minimumColor"
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
    line-height: 1;
    padding-bottom: 0;
}

.heatmap-container :deep(.n-heatmap) {
    min-width: fit-content;
}

.heatmap-container :deep(.n-heatmap__calendar-table) {
    font-variant-numeric: tabular-nums;
}
</style>
