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
            <RouterLink
                class="stat-cell autopilot-cell autopilot-link"
                :to="{ name: 'controlCenterAutopilot' }"
                aria-label="Open Autopilot page"
            >
                <div class="stacked-stat autopilot-stat">
                    <span class="autopilot-label">Autopilot mode</span>
                    <span
                        class="autopilot-value"
                        :class="autopilot_class"
                    >
                        {{ autopilot_mode_label }}
                    </span>
                    <span v-if="autopilot_summary" class="autopilot-subtext">{{ autopilot_summary }}</span>
                    <span v-if="green_phase_hint" class="autopilot-detail">{{ green_phase_hint }}</span>
                </div>
            </RouterLink>
            <div class="stat-cell">
                <n-statistic label="Funds locked" :value="formatFixed2(funds_locked)" />
            </div>
            <div class="stat-cell">
                <div class="stacked-stat funds-stat">
                    <span class="funds-label">Funds available</span>
                    <span class="funds-value">
                        {{ formatOptionalFixed2(funds_tradable) }}
                    </span>
                    <span class="stat-detail">
                        Exchange free {{ formatOptionalFixed2(funds_available) }}
                    </span>
                    <span v-if="capital_available_quote !== null" class="stat-detail">
                        Budget headroom {{ formatFixed2(Math.max(0, capital_available_quote)) }}
                    </span>
                </div>
            </div>
        </div>
    </n-flex>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { useWebSocketDataStore } from '../stores/websocket'
import { storeToRefs } from 'pinia'
import { formatAutopilotMemoryHint } from '../autopilot/presentation'
const statistics_store = useWebSocketDataStore("statistics")
const statistics_data = storeToRefs(statistics_store)
const hasStatisticsData = computed(() => statistics_data.hasReceivedData.value)
const profit_overall = ref(0)
const profit_class = ref<'green' | 'red'>('green')
const upnl = ref(0)
const upnl_class = ref<'green' | 'red'>('green')
const funds_locked = ref(0)
const funds_available = ref<number | null>(null)
const funds_tradable = ref<number | null>(null)
const capital_available_quote = ref<number | null>(null)
const autopilot_class = ref<'green' | 'red' | 'orange' | 'muted'>('muted')
const autopilot_state = ref<'high' | 'medium' | 'low' | 'none'>('none')
const autopilot_effective_max_bots = ref(0)
const autopilot_green_phase_detected = ref(false)
const autopilot_green_phase_active = ref(false)
const autopilot_green_phase_extra_deals = ref(0)
const autopilot_green_phase_block_reason = ref<string | null>(null)
const autopilot_memory_status = ref<string | null>(null)
const autopilot_memory_stale = ref(false)
const autopilot_memory_stale_reason = ref<string | null>(null)
const autopilot_memory_current_closes = ref(0)
const autopilot_memory_required_closes = ref(0)

const autopilot_summary = computed(() => {
    if (autopilot_state.value === 'none') {
        return ''
    }
    return `Effective max bots ${autopilot_effective_max_bots.value}`
})

const autopilot_mode_label = computed(() => {
    if (autopilot_state.value === 'none') {
        return 'Disabled'
    }
    return autopilot_state.value.charAt(0).toUpperCase() + autopilot_state.value.slice(1)
})

const green_phase_hint = computed(() => {
    if (autopilot_state.value === 'none') {
        return ''
    }
    if (autopilot_memory_stale.value || autopilot_memory_status.value === 'warming_up') {
        return formatAutopilotMemoryHint({
            currentCloses: autopilot_memory_current_closes.value,
            requiredCloses: autopilot_memory_required_closes.value,
            stale: autopilot_memory_stale.value,
            staleReason: autopilot_memory_stale_reason.value,
            status: autopilot_memory_status.value,
        })
    }
    if (autopilot_green_phase_active.value) {
        return `Green phase active (+${autopilot_green_phase_extra_deals.value} deals)`
    }
    if (autopilot_green_phase_detected.value && autopilot_green_phase_block_reason.value) {
        return `Green phase blocked: ${formatBlockReason(autopilot_green_phase_block_reason.value)}`
    }
    return 'Green phase idle'
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
        funds_available.value = toOptionalNumber(websocket_data.funds_available)
        capital_available_quote.value = toOptionalNumber(
            websocket_data.capital_available_quote,
        )
        funds_tradable.value =
            toOptionalNumber(websocket_data.funds_tradable) ??
            deriveTradableFunds(
                funds_available.value,
                capital_available_quote.value,
                websocket_data.capital_budget_reason,
            )
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
        autopilot_memory_status.value =
            typeof websocket_data.autopilot_memory_status === 'string'
                ? websocket_data.autopilot_memory_status
                : null
        autopilot_memory_stale.value = Boolean(
            websocket_data.autopilot_memory_stale,
        )
        autopilot_memory_stale_reason.value =
            typeof websocket_data.autopilot_memory_stale_reason === 'string'
                ? websocket_data.autopilot_memory_stale_reason
                : null
        autopilot_memory_current_closes.value = toNumberOrZero(
            websocket_data.autopilot_memory_current_closes,
        )
        autopilot_memory_required_closes.value = toNumberOrZero(
            websocket_data.autopilot_memory_required_closes,
        )
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

function toOptionalNumber(value: unknown): number | null {
    if (value === null || value === undefined) {
        return null
    }
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : null
}

function deriveTradableFunds(
    exchangeAvailable: number | null,
    capitalAvailable: number | null,
    capitalReason: unknown,
): number | null {
    if (exchangeAvailable === null) {
        return null
    }
    if (
        capitalAvailable === null ||
        capitalReason === 'capital_budget_unconfigured'
    ) {
        return Math.max(0, exchangeAvailable)
    }
    return Math.min(Math.max(0, exchangeAvailable), Math.max(0, capitalAvailable))
}

function formatFixed2(value: number): string {
    return value.toFixed(2)
}

function formatOptionalFixed2(value: number | null): string {
    return value === null ? 'Unavailable' : formatFixed2(value)
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
    min-height: 92px;
    padding: 16px;
    border: 1px solid var(--mw-color-border);
    border-radius: var(--mw-radius-md, 10px);
    background: var(--mw-surface-card);
    display: flex;
    align-items: stretch;
    justify-content: flex-start;
    box-shadow: var(--mw-shadow-card);
}

.stat-detail {
    color: var(--mw-color-text-muted);
    font-size: 12px;
    line-height: 1.25;
    text-align: left;
    overflow-wrap: anywhere;
}

:deep(.n-statistic) {
    width: 100%;
    text-align: left;
}

:deep(.n-statistic__label) {
    color: var(--mw-color-text-muted);
    font-size: 12px;
    font-weight: 450;
    letter-spacing: 0.075em;
    line-height: 1.2;
    text-transform: uppercase;
}

:deep(.n-statistic-value) {
    color: var(--mw-color-text-primary);
    font-family: var(--mw-font-mono);
    font-size: 23px;
    font-weight: 450;
    font-variant-numeric: tabular-nums;
    line-height: 1.12;
    margin-top: 6px;
}

:deep(.n-statistic-value__content) {
    font-weight: 450;
}

.red {
     --n-value-text-color: #B4443F !important;
}

.green {
     --n-value-text-color: #2E7D5B !important;
}

.orange {
     --n-value-text-color: #B7791F !important;
}

.stacked-stat {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    justify-content: flex-start;
    text-align: left;
    gap: 6px;
    height: 100%;
    width: 100%;
}

.funds-value {
    color: var(--n-value-text-color);
    font-family: var(--mw-font-mono);
    font-size: 23px;
    font-weight: 450;
    font-variant-numeric: tabular-nums;
    line-height: 1.15;
}

.autopilot-value {
    color: var(--mw-color-text-primary);
    font-family: var(--mw-font-display);
    font-size: 23px;
    font-weight: 450;
    line-height: 1.12;
    margin-top: 6px;
}

.autopilot-cell {
    cursor: pointer;
    transition:
        border-color 120ms ease,
        box-shadow 120ms ease,
        transform 120ms ease;
}

.autopilot-link {
    color: inherit;
    text-decoration: none;
}

.autopilot-cell:hover,
.autopilot-cell:focus-visible {
    border-color: rgba(29, 92, 73, 0.26);
    box-shadow: 0 10px 24px rgba(24, 33, 29, 0.08);
    transform: translateY(-1px);
}

.autopilot-label,
.funds-label {
    color: var(--mw-color-text-muted);
    font-size: 12px;
    font-weight: 450;
    letter-spacing: 0.075em;
    line-height: 1.2;
    text-transform: uppercase;
}

.autopilot-subtext,
.autopilot-detail {
    font-size: 12px;
    color: var(--mw-color-text-muted);
}

.autopilot-value.red {
    color: #B4443F;
}

.autopilot-value.orange {
    color: #B7791F;
}

.muted {
    color: var(--mw-color-text-muted);
}

@media (max-width: 768px) {
    .statistics-grid {
        grid-template-columns: repeat(2, minmax(0, 1fr));
        overflow: visible;
        gap: 8px;
    }

    .stat-cell {
        min-width: 0;
        min-height: 82px;
        padding: 12px;
        border-radius: 6px;
    }

    :deep(.n-statistic__label) {
        font-size: 12px;
        line-height: 1.2;
    }

    :deep(.n-statistic-value) {
        font-size: 24px;
        line-height: 1.15;
    }

    .autopilot-label,
    .funds-label {
        font-size: 12px;
        line-height: 1.2;
    }

}

@media (min-width: 769px) and (max-width: 1200px) {
      .statistics-grid {
         grid-template-columns: repeat(2, minmax(0, 1fr));
      }
}

@media (max-width: 520px) {
    .statistics-grid {
        grid-template-columns: 1fr;
        gap: 12px;
    }
}
</style>
