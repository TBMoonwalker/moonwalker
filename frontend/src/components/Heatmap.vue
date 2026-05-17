<script setup lang="ts">
import { computed, ref } from 'vue'

const props = defineProps<{
   data: { timestamp: number; value: number }[]
}>()

const hoveredCell = ref<string | null>(null)
const tooltipText = ref('')
const tooltipX = ref(0)
const tooltipY = ref(0)

const CELL_W = 11
const CELL_GAP = 3
const DAY_OF_WEEK_LABELS = ['', 'Mon', '', 'Wed', '', 'Fri', '']
const MONTH_NAMES = [
      'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
      'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
]

interface Cell {
    date: Date
    dateKey: string
    value: number
}

interface Week {
    cells: (Cell | null)[]
}

interface MonthLabel {
    label: string
    colIndex: number
}

const heatmapData = computed(() => {
    if (!props.data.length) return null

    const tradeMap = new Map<string, number>()
    for (const d of props.data) {
        const date = new Date(d.timestamp)
        const key = dayKey(date)
        tradeMap.set(key, (tradeMap.get(key) || 0) + d.value)
     }

    let [first, last] = [Infinity, -Infinity] as [number, number]
    for (const [key] of tradeMap) {
        const ts = Date.parse(`${key}T00:00:00`)
        if (ts < first) first = ts
        if (ts > last) last = ts
     }

    const max = Math.max(0, ...tradeMap.values())

    const allDays: Cell[] = []
    const cursor = new Date(first)
    const end = new Date(last)
    while (cursor <= end) {
        const key = dayKey(cursor)
        allDays.push({
            date: new Date(cursor),
            dateKey: key,
            value: tradeMap.get(key) || 0,
        })
        cursor.setDate(cursor.getDate() + 1)
     }

    const weeks: Week[] = []
    for (let i = 0; i < allDays.length; i += 7) {
        const chunk = allDays.slice(i, i + 7)
        const padStart = chunk[0].date.getDay()
        const padEnd = Math.max(0, 7 - chunk.length)
        weeks.push({
            cells: [
                ...Array(padStart).fill(null),
                ...chunk.map((d) => d),
                ...Array(padEnd).fill(null),
            ],
        })
     }

    const firstDow = allDays[0]?.date.getDay() ?? 0
    const monthLabels: MonthLabel[] = [{
        label: MONTH_NAMES[allDays[0].date.getMonth()],
        colIndex: 0,
     }]
    let prevMonth = allDays[0].date.getMonth()
    for (let i = 1; i < allDays.length; i++) {
        const m = allDays[i].date.getMonth()
        if (m !== prevMonth) {
            monthLabels.push({
                label: MONTH_NAMES[m],
                colIndex: firstDow + i,
            })
            prevMonth = m
         }
     }

    return {
        weeks,
        monthLabels,
        max,
        firstDow,
      }
})

function dayKey(d: Date): string {
    return d.toISOString().slice(0, 10)
}

function cellColor(value: number, max: number): string {
    if (max === 0) return 'rgb(29, 92, 73)'
    const t = value / max
    const r = Math.round(29 + t * (46 - 29))
    const g = Math.round(92 + t * (125 - 92))
    const b = Math.round(73 + t * (91 - 73))
    return `rgb(${r}, ${g}, ${b})`
}

function onEnter(cell: Cell, e: MouseEvent) {
    hoveredCell.value = cell.dateKey
    tooltipText.value = `${cell.value} trades on ${cell.date.toLocaleDateString()}`
    tooltipX.value = e.pageX - 80
    tooltipY.value = e.pageY - 40
}

function onLeave() {
    hoveredCell.value = null
}

function getDayLabel(weekIndex: number, firstDow: number): string {
    const dow = (firstDow + weekIndex) % 7
    return DAY_OF_WEEK_LABELS[dow] ?? ''
}
</script>

<template>
    <div v-if="!heatmapData" class="heatmap-empty">
        <n-empty description="No data to display" />
    </div>
    <div v-else class="heatmap-container">
        <div class="heatmap-grid">
             <div class="heatmap-days">
                 <div
                    v-for="(_, wi) in heatmapData.weeks"
                    :key="`r-${wi}`"
                    class="heatmap-day-row"
                 >
                     <span
                        v-if="getDayLabel(wi, heatmapData.firstDow)"
                        class="day-label"
                     >{{ getDayLabel(wi, heatmapData.firstDow) }}</span>
                 </div>
             </div>

            <div class="heatmap-body">
                <div class="heatmap-months">
                    <span
                        v-for="(ml, mi) in heatmapData.monthLabels"
                        :key="mi"
                        class="month-label"
                        :style="{ marginLeft: `${ml.colIndex * (CELL_W + CELL_GAP)}px` }"
                    >{{ ml.label }}</span>
                </div>

                <div class="heatmap-weeks">
                    <div v-for="(week, wi) in heatmapData.weeks" :key="wi" class="heatmap-week">
                        <div
                            v-for="(cell, ci) in week.cells"
                            :key="`${wi}-${ci}`"
                            class="heatmap-cell"
                            :class="{
                                'is-empty': cell === null,
                                'is-hovered': cell && cell.dateKey === hoveredCell,
                            }"
                            :style="cell ? { backgroundColor: cellColor(cell.value, heatmapData.max) } : {}"
                            @mouseenter="cell && onEnter(cell, $event)"
                            @mouseleave="onLeave"
                        />
                    </div>
                </div>
            </div>
        </div>

        <div
            v-if="hoveredCell && tooltipText"
            class="heatmap-tooltip"
            :style="{ left: `${tooltipX}px`, top: `${tooltipY}px` }"
        >{{ tooltipText }}</div>
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
    position: relative;
    width: 100%;
    overflow-x: auto;
}

.heatmap-grid {
    display: flex;
    min-width: fit-content;
}

.heatmap-days {
    display: flex;
    flex-direction: column;
    padding-right: 6px;
    flex-shrink: 0;
}

.heatmap-day-row {
    height: 16px;
    display: flex;
    align-items: center;
    justify-content: flex-end;
}

.day-label {
    font-size: 10px;
    color: rgba(255, 255, 255, 0.45);
    line-height: 1;
}

.heatmap-body {
    display: flex;
    flex-direction: column;
}

.heatmap-months {
    height: 22px;
    position: relative;
}

.month-label {
    position: absolute;
    font-size: 11px;
    color: rgba(255, 255, 255, 0.55);
    line-height: 1;
}

.heatmap-weeks {
    display: flex;
    flex-direction: column;
}

.heatmap-week {
    display: flex;
    gap: 3px;
}

.heatmap-cell {
    width: 11px;
    height: 14px;
    border-radius: 2px;
    cursor: default;
    transition: outline-color 80ms ease;
}

.heatmap-cell.is-empty {
    visibility: hidden;
}

.heatmap-cell.is-hovered {
    outline: 1px solid rgba(255, 255, 255, 0.6);
}

.heatmap-tooltip {
    position: absolute;
    background: rgba(30, 30, 30, 0.95);
    color: rgba(255, 255, 255, 0.9);
    padding: 4px 8px;
    border-radius: 4px;
    font-size: 11px;
    pointer-events: none;
    white-space: nowrap;
    z-index: 10;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.4);
}
</style>
