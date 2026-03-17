<template>
    <n-flex vertical :size="8" class="statistics-shell">
        <n-alert
            v-if="!hasStatisticsData"
            title="Waiting for live statistics..."
            type="info"
            role="status"
            aria-live="polite"
        />
        <div class="statistics-grid">
            <div class="stat-cell">
                <n-statistic
                    :class="profit_class"
                    label="Profit overall"
                    :value="formatFixed2(profit_overall)"
                />
            </div>
            <div class="stat-cell">
                <n-statistic
                    :class="upnl_class"
                    label="UPNL"
                    :value="formatFixed2(upnl)"
                />
            </div>
            <div class="stat-cell autopilot-cell">
                <div class="autopilot-stat">
                    <span class="autopilot-label">Autopilot mode</span>
                    <span
                        class="autopilot-icon"
                        :class="autopilot_class"
                        role="img"
                        :aria-label="autopilot_aria_label"
                    >
                        <n-icon size="34">
                            <component :is="autopilot_icon" />
                        </n-icon>
                    </span>
                    <span class="autopilot-subtext">{{ autopilot_summary }}</span>
                    <span v-if="green_phase_hint" class="autopilot-detail">{{ green_phase_hint }}</span>
                </div>
            </div>
            <div class="stat-cell">
                <n-statistic label="Funds locked" :value="formatFixed2(funds_locked)" />
            </div>
            <div class="stat-cell">
                <n-statistic label="Funds available" :value="formatFixed2(funds_available)" />
            </div>
        </div>
    </n-flex>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useWebSocketDataStore } from '../stores/websocket'
import { storeToRefs } from 'pinia'
import {
    AlertCircleOutline,
    CheckmarkCircleOutline,
    PauseCircleOutline,
    WarningOutline,
} from '@vicons/ionicons5'

const statistics_store = useWebSocketDataStore("statistics")
const statistics_data = storeToRefs(statistics_store)
const hasStatisticsData = computed(() => statistics_data.hasReceivedData.value)
const profit_overall = ref(0)
const profit_class = ref<'green' | 'red'>('green')
const upnl = ref(0)
const upnl_class = ref<'green' | 'red'>('green')
const funds_locked = ref(0)
const funds_available = ref(0)
const autopilot_class = ref<'green' | 'red' | 'orange' | 'muted'>('muted')
const autopilot_state = ref<'high' | 'medium' | 'low' | 'none'>('none')
const autopilot_effective_max_bots = ref(0)
const autopilot_green_phase_detected = ref(false)
const autopilot_green_phase_active = ref(false)
const autopilot_green_phase_extra_deals = ref(0)
const autopilot_green_phase_block_reason = ref<string | null>(null)

const autopilot_summary = computed(() => {
    if (autopilot_state.value === 'none') {
        return 'Disabled'
    }
    return `Effective max bots ${autopilot_effective_max_bots.value}`
})

const green_phase_hint = computed(() => {
    if (autopilot_state.value === 'none') {
        return ''
    }
    if (autopilot_green_phase_active.value) {
        return `Green phase active (+${autopilot_green_phase_extra_deals.value} deals)`
    }
    if (autopilot_green_phase_detected.value && autopilot_green_phase_block_reason.value) {
        return `Green phase blocked: ${formatBlockReason(autopilot_green_phase_block_reason.value)}`
    }
    return 'Green phase idle'
})

const autopilot_icon = computed(() => {
    if (autopilot_state.value === 'high') {
        return AlertCircleOutline
    }
    if (autopilot_state.value === 'medium') {
        return WarningOutline
    }
    if (autopilot_state.value === 'low') {
        return CheckmarkCircleOutline
    }
    return PauseCircleOutline
})

const autopilot_aria_label = computed(() => {
    if (autopilot_state.value === 'high') {
        return 'Autopilot mode high'
    }
    if (autopilot_state.value === 'medium') {
        return 'Autopilot mode medium'
    }
    if (autopilot_state.value === 'low') {
        return 'Autopilot mode low'
    }
    return 'Autopilot disabled'
})

// Get new statistics data
watch(statistics_data.data, (newData) => {
    if (newData !== undefined && newData !== null) {
        const websocket_data = newData as any
        upnl.value = toNumberOrZero(websocket_data.upnl)
        upnl_class.value = row_classes(upnl.value)
        profit_overall.value = toNumberOrZero(websocket_data.profit_overall)
        profit_class.value = row_classes(profit_overall.value)
        funds_locked.value = toNumberOrZero(websocket_data.funds_locked)
        funds_available.value = toNumberOrZero(websocket_data.funds_available)
        autopilot_effective_max_bots.value =
            toNumberOrZero(websocket_data.autopilot_effective_max_bots)
        autopilot_green_phase_detected.value =
            Boolean(websocket_data.autopilot_green_phase_detected)
        autopilot_green_phase_active.value =
            Boolean(websocket_data.autopilot_green_phase_active)
        autopilot_green_phase_extra_deals.value =
            toNumberOrZero(websocket_data.autopilot_green_phase_extra_deals)
        autopilot_green_phase_block_reason.value =
            typeof websocket_data.autopilot_green_phase_block_reason === 'string'
                ? websocket_data.autopilot_green_phase_block_reason
                : null
        if (websocket_data.autopilot == "high") {
            autopilot_state.value = 'high'
            autopilot_class.value = "red"
        } else if (websocket_data.autopilot == "medium") {
            autopilot_state.value = 'medium'
            autopilot_class.value = "orange"
        } else if (websocket_data.autopilot == "low") {
            autopilot_state.value = 'low'
            autopilot_class.value = "green"
        } else {
            autopilot_state.value = 'none'
            autopilot_class.value = "muted"
        }

    }

}, { immediate: true })

function row_classes(data: number): 'green' | 'red' {
    if (Math.sign(data) >= 0) {
        return 'green'
    } else {
        return 'red'
    }
}

function toNumberOrZero(value: unknown): number {
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : 0
}

function formatFixed2(value: number): string {
    return value.toFixed(2)
}

function formatBlockReason(value: string): string {
    return value.replaceAll('_', ' ')
}

</script>

<style scoped>
.statistics-shell {
    width: 100%;
}

.statistics-grid {
    width: 100%;
    display: grid;
    grid-template-columns: repeat(5, minmax(0, 1fr));
    gap: 12px;
}

.stat-cell {
    min-width: 0;
    padding: 6px 10px;
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 8px;
    background: rgba(255, 255, 255, 0.02);
    display: flex;
    align-items: center;
    justify-content: center;
}

:deep(.n-statistic) {
    width: 100%;
    text-align: center;
}

:deep(.n-statistic-value) {
    font-variant-numeric: tabular-nums;
}

.red {
    --n-value-text-color: rgb(224, 108, 117) !important;
}

.green {
    --n-value-text-color: rgb(99, 226, 183) !important;
}

.orange {
    --n-value-text-color: rgb(240, 173, 78) !important;
}

.autopilot-stat {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    text-align: center;
    gap: 6px;
    height: 100%;
    width: 100%;
}

.autopilot-label {
    font-size: 14px;
    color: var(--n-label-text-color, rgba(255, 255, 255, 0.65));
}

.autopilot-subtext,
.autopilot-detail {
    font-size: 12px;
    color: rgba(255, 255, 255, 0.72);
}

.autopilot-icon {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 100%;
    line-height: 1;
}

.autopilot-icon.red {
    color: rgb(224, 108, 117);
}

.autopilot-icon.orange {
    color: rgb(240, 173, 78);
}

.muted {
    color: rgba(255, 255, 255, 0.5);
}

@media (max-width: 768px) {
    .autopilot-cell {
        display: none;
    }

    .statistics-grid {
        grid-template-columns: none;
        grid-auto-flow: column;
        grid-auto-columns: minmax(118px, 1fr);
        overflow-x: auto;
        overflow-y: hidden;
        gap: 8px;
        padding-bottom: 2px;
        scroll-snap-type: x proximity;
        -webkit-overflow-scrolling: touch;
    }

    .stat-cell {
        min-width: 0;
        padding: 4px 6px;
        border-radius: 6px;
        scroll-snap-align: start;
    }

    :deep(.n-statistic-label) {
        font-size: 12px;
        line-height: 1.2;
    }

    :deep(.n-statistic-value) {
        font-size: 30px;
    }

    .autopilot-label {
        font-size: 12px;
        line-height: 1.2;
    }

    .autopilot-icon :deep(svg) {
        width: 28px;
        height: 28px;
    }

    .statistics-grid::-webkit-scrollbar {
        height: 6px;
    }

    .statistics-grid::-webkit-scrollbar-thumb {
        background: rgba(255, 255, 255, 0.18);
        border-radius: 999px;
    }
}

@media (min-width: 769px) and (max-width: 1200px) {
    .statistics-grid {
        grid-template-columns: repeat(3, minmax(0, 1fr));
    }
}
</style>
