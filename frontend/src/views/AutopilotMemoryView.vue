<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import {
    formatAutopilotConfidenceBadge,
    formatAutopilotEvent,
    formatAutopilotFeaturedInsight,
    formatAutopilotReason,
    formatAutopilotStatusBody,
    formatAutopilotStatusTitle,
    formatAutopilotTimestamp,
} from '../autopilot/presentation'
import type { AutopilotMemorySnapshot } from '../autopilot/types'
import { useAutopilotMemoryFeed } from '../composables/useAutopilotMemoryFeed'

const router = useRouter()
const { data, error, loading, refresh } = useAutopilotMemoryFeed()
const selectedSymbol = ref<string | null>(null)

const allRows = computed(() => {
    const payload = data.value
    if (!payload) {
        return []
    }
    return [...payload.trust_board.favored, ...payload.trust_board.cooling]
})

watch(
    allRows,
    (rows) => {
        if (!rows.length) {
            selectedSymbol.value = null
            return
        }
        if (selectedSymbol.value && rows.some((row) => row.symbol === selectedSymbol.value)) {
            return
        }
        selectedSymbol.value = data.value?.featured?.symbol ?? rows[0].symbol
    },
    { immediate: true },
)

const selectedSnapshot = computed<AutopilotMemorySnapshot | null>(() => {
    if (!selectedSymbol.value) {
        return null
    }
    return allRows.value.find((row) => row.symbol === selectedSymbol.value) ?? null
})

function openControlCenterOverview(): void {
    void router.push({
        name: 'controlCenter',
        query: {
            mode: 'overview',
        },
    })
}

function openAutopilotAdvanced(): void {
    void router.push({
        name: 'controlCenter',
        query: {
            mode: 'advanced',
            target: 'autopilot',
        },
    })
}
</script>

<template>
    <div class="page-shell autopilot-memory-page">
        <n-flex class="page-header" justify="space-between" align="start" :wrap="true" :size="[12, 12]">
            <div class="page-copy">
                <n-text depth="3">Control Center / Autopilot</n-text>
                <h1 class="page-title">{{ formatAutopilotStatusTitle(data) }}</h1>
                <p class="page-summary">
                    {{ formatAutopilotStatusBody(data) }}
                </p>
            </div>
            <div class="page-actions">
                <n-button secondary @click="openControlCenterOverview">
                    Back to Control Center
                </n-button>
                <n-button type="primary" secondary @click="openAutopilotAdvanced">
                    Tune Autopilot
                </n-button>
            </div>
        </n-flex>

        <n-alert
            v-if="error"
            type="warning"
            title="Autopilot memory could not be loaded"
            :bordered="false"
        >
            {{ error }}
            <template #action>
                <n-button text @click="refresh">Retry</n-button>
            </template>
        </n-alert>

        <template v-else-if="loading && !data">
            <n-card>
                <n-skeleton text :repeat="6" />
            </n-card>
        </template>

        <template v-else-if="data">
            <n-alert
                v-if="data.stale || data.status === 'warming_up' || !data.enabled"
                :type="data.stale ? 'warning' : 'info'"
                :bordered="false"
                :title="
                    data.stale
                        ? 'Baseline behavior active'
                        : data.status === 'warming_up'
                          ? 'Autopilot is still learning'
                          : 'Autopilot is disabled'
                "
            >
                {{
                    data.stale
                        ? 'Moonwalker kept the last known ranking visible while adaptive TP falls back to baseline behavior.'
                        : data.status === 'warming_up'
                          ? `Learning from ${data.warmup.current_closes} of ${data.warmup.required_closes} closes before symbol trust becomes active.`
                          : 'Moonwalker is still collecting symbol memory, but it is not applying it yet.'
                }}
            </n-alert>

            <n-card
                v-if="data.status === 'warming_up'"
                class="page-section-card"
                content-style="padding: 18px 20px;"
            >
                <n-flex vertical :size="10">
                    <div>
                        <h2 class="section-title">Warm-up progress</h2>
                        <n-text depth="3">
                            Learning from {{ data.warmup.current_closes }} of
                            {{ data.warmup.required_closes }} closes.
                        </n-text>
                    </div>
                    <n-progress
                        type="line"
                        :percentage="data.warmup.progress_percent ?? 0"
                        :show-indicator="false"
                        status="success"
                    />
                </n-flex>
            </n-card>

            <div class="grid-shell">
                <n-card class="page-section-card" content-style="padding: 18px 20px;">
                    <n-flex vertical :size="14">
                        <div>
                            <h2 class="section-title">Trust board</h2>
                            <n-text depth="3">
                                Current strongest trust moves, ranked from the latest persisted memory snapshot.
                            </n-text>
                        </div>
                        <div class="board-columns">
                            <section>
                                <h3 class="column-title">Favored</h3>
                                <button
                                    v-for="row in data.trust_board.favored"
                                    :key="row.symbol"
                                    class="trust-row trust-row-positive"
                                    type="button"
                                    @click="selectedSymbol = row.symbol"
                                >
                                    <span>
                                        <strong>{{ row.symbol }}</strong>
                                        <small>{{ formatAutopilotReason(row.primary_reason_code, row.primary_reason_value) }}</small>
                                    </span>
                                    <span class="trust-row-meta">
                                        {{ formatAutopilotConfidenceBadge(row.confidence_bucket) }}
                                        · {{ row.trust_score.toFixed(1) }}
                                    </span>
                                </button>
                            </section>

                            <section>
                                <h3 class="column-title">Cooling</h3>
                                <button
                                    v-for="row in data.trust_board.cooling"
                                    :key="row.symbol"
                                    class="trust-row trust-row-warning"
                                    type="button"
                                    @click="selectedSymbol = row.symbol"
                                >
                                    <span>
                                        <strong>{{ row.symbol }}</strong>
                                        <small>{{ formatAutopilotReason(row.primary_reason_code, row.primary_reason_value) }}</small>
                                    </span>
                                    <span class="trust-row-meta">
                                        {{ formatAutopilotConfidenceBadge(row.confidence_bucket) }}
                                        · {{ row.trust_score.toFixed(1) }}
                                    </span>
                                </button>
                            </section>
                        </div>
                    </n-flex>
                </n-card>

                <n-card class="page-section-card" content-style="padding: 18px 20px;">
                    <n-flex vertical :size="14">
                        <div>
                            <h2 class="section-title">Selected symbol</h2>
                            <n-text depth="3">
                                {{
                                    selectedSnapshot
                                        ? formatAutopilotFeaturedInsight(selectedSnapshot)
                                        : 'No symbol is selected yet.'
                                }}
                            </n-text>
                        </div>

                        <template v-if="selectedSnapshot">
                            <div class="selected-grid">
                                <div class="selected-metric">
                                    <span class="metric-label">Confidence</span>
                                    <strong>{{ formatAutopilotConfidenceBadge(selectedSnapshot.confidence_bucket) }}</strong>
                                </div>
                                <div class="selected-metric">
                                    <span class="metric-label">Trust score</span>
                                    <strong>{{ selectedSnapshot.trust_score.toFixed(1) }}</strong>
                                </div>
                                <div class="selected-metric">
                                    <span class="metric-label">Suggested TP delta</span>
                                    <strong>{{ (selectedSnapshot.tp_delta_ratio * 100).toFixed(0) }}%</strong>
                                </div>
                                <div class="selected-metric">
                                    <span class="metric-label">Suggested BO</span>
                                    <strong>{{ selectedSnapshot.suggested_base_order.toFixed(2) }}</strong>
                                </div>
                            </div>

                            <div class="reason-list">
                                <p>
                                    <strong>Primary reason:</strong>
                                    {{ formatAutopilotReason(selectedSnapshot.primary_reason_code, selectedSnapshot.primary_reason_value) }}
                                </p>
                                <p v-if="selectedSnapshot.secondary_reason_code">
                                    <strong>Secondary note:</strong>
                                    {{ formatAutopilotReason(selectedSnapshot.secondary_reason_code, selectedSnapshot.secondary_reason_value) }}
                                </p>
                                <p>
                                    <strong>Last close:</strong>
                                    {{ formatAutopilotTimestamp(selectedSnapshot.last_closed_at) }}
                                </p>
                            </div>
                        </template>
                    </n-flex>
                </n-card>
            </div>

            <n-card class="page-section-card" content-style="padding: 18px 20px;">
                <n-flex vertical :size="14">
                    <div>
                        <h2 class="section-title">Latest Autopilot moves</h2>
                        <n-text depth="3">
                            Recent evidence for what Moonwalker changed or noticed.
                        </n-text>
                    </div>

                    <div v-if="data.events.length" class="event-list">
                        <div
                            v-for="event in data.events"
                            :key="`${event.created_at}-${event.event_type}-${event.symbol}`"
                            class="event-row"
                        >
                            <div>
                                <p class="event-copy">{{ formatAutopilotEvent(event) }}</p>
                                <small>{{ formatAutopilotTimestamp(event.created_at) }}</small>
                            </div>
                        </div>
                    </div>
                    <n-empty
                        v-else
                        description="Moonwalker has not recorded any Autopilot memory events yet."
                    />
                </n-flex>
            </n-card>
        </template>
    </div>
</template>

<style scoped>
.autopilot-memory-page {
    display: flex;
    flex-direction: column;
    gap: 16px;
}

.page-header {
    margin-bottom: 4px;
}

.page-copy {
    max-width: 62ch;
}

.page-title {
    margin: 6px 0 8px;
    color: var(--mw-color-text-primary);
    font-family: var(--mw-font-display);
    font-size: 2rem;
    font-weight: 700;
    letter-spacing: -0.03em;
}

.page-summary {
    margin: 0;
    color: var(--mw-color-text-secondary);
    font-family: var(--mw-font-body);
    font-size: 1rem;
    line-height: 1.6;
}

.page-actions {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
}

.page-section-card {
    border-color: rgba(29, 92, 73, 0.14);
}

.section-title,
.column-title {
    margin: 0 0 6px;
    color: var(--mw-color-text-primary);
    font-family: var(--mw-font-display);
    letter-spacing: -0.02em;
}

.grid-shell {
    display: grid;
    gap: 16px;
    grid-template-columns: minmax(0, 1.3fr) minmax(0, 1fr);
}

.board-columns {
    display: grid;
    gap: 14px;
    grid-template-columns: repeat(2, minmax(0, 1fr));
}

.trust-row {
    width: 100%;
    padding: 12px 14px;
    border-radius: 10px;
    border: 1px solid var(--mw-color-border-subtle, #d5dbd5);
    background: #f7f8f6;
    color: var(--mw-color-text-primary);
    display: flex;
    justify-content: space-between;
    align-items: center;
    text-align: left;
    gap: 12px;
    cursor: pointer;
}

.trust-row strong,
.trust-row small {
    display: block;
}

.trust-row small {
    margin-top: 4px;
    color: var(--mw-color-text-secondary);
    font-family: var(--mw-font-body);
    font-size: 0.85rem;
}

.trust-row-positive {
    border-color: rgba(46, 125, 91, 0.22);
}

.trust-row-warning {
    border-color: rgba(183, 121, 31, 0.22);
}

.trust-row-meta {
    color: var(--mw-color-text-secondary);
    font-family: var(--mw-font-mono);
    font-size: 0.82rem;
    white-space: nowrap;
}

.selected-grid {
    display: grid;
    gap: 12px;
    grid-template-columns: repeat(2, minmax(0, 1fr));
}

.selected-metric {
    padding: 12px 14px;
    border-radius: 10px;
    background: #f7f8f6;
    border: 1px solid var(--mw-color-border-subtle, #d5dbd5);
}

.metric-label {
    display: block;
    margin-bottom: 6px;
    color: var(--mw-color-text-secondary);
    font-size: 0.84rem;
}

.reason-list p,
.event-copy {
    margin: 0 0 8px;
}

.event-list {
    display: grid;
    gap: 10px;
}

.event-row {
    padding: 12px 14px;
    border-radius: 10px;
    background: #f7f8f6;
    border: 1px solid var(--mw-color-border-subtle, #d5dbd5);
}

@media (max-width: 900px) {
    .grid-shell,
    .board-columns,
    .selected-grid {
        grid-template-columns: 1fr;
    }

    .page-actions {
        width: 100%;
    }

    .page-actions :deep(.n-button) {
        flex: 1 1 auto;
    }
}
</style>
