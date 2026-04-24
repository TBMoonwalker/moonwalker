<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import {
    formatAutopilotConfidenceBadge,
    formatAutopilotEntrySizingBody,
    formatAutopilotEntrySizingTitle,
    formatAutopilotEvent,
    formatAutopilotFeaturedInsight,
    formatAutopilotReason,
    formatAutopilotStatusBody,
    formatAutopilotStatusTitle,
    formatAutopilotTimestamp,
} from '../autopilot/presentation'
import { splitTradeSymbol } from '../helpers/openTrades'
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

function formatTrustBoardSymbol(symbol: string): string {
    return splitTradeSymbol(symbol)[0] || symbol
}
</script>

<template>
    <div class="page-shell autopilot-memory-page">
        <n-card class="autopilot-shell mw-shell-card" content-style="padding: 18px 20px;">
            <n-flex vertical :size="16">
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
                    <n-card class="page-section-card mw-muted-card" content-style="padding: 18px 20px;">
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
                        class="page-section-card mw-muted-card"
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
                        <n-card class="page-section-card mw-muted-card" content-style="padding: 18px 20px;">
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
                                            :aria-pressed="selectedSymbol === row.symbol"
                                            @click="selectedSymbol = row.symbol"
                                        >
                                            <span class="trust-row-copy">
                                                <strong class="trust-row-symbol">
                                                    {{ formatTrustBoardSymbol(row.symbol) }}
                                                </strong>
                                                <small>{{ formatAutopilotReason(row.primary_reason_code, row.primary_reason_value) }}</small>
                                            </span>
                                            <span class="trust-row-meta">
                                                {{ formatAutopilotConfidenceBadge(row.confidence_bucket) }}
                                                · {{ row.trust_score.toFixed(1) }}
                                            </span>
                                        </button>
                                        <div
                                            v-if="!data.trust_board.favored.length"
                                            class="trust-empty"
                                        >
                                            No favored symbols in the latest snapshot.
                                        </div>
                                    </section>

                                    <section>
                                        <h3 class="column-title">Cooling</h3>
                                        <button
                                            v-for="row in data.trust_board.cooling"
                                            :key="row.symbol"
                                            class="trust-row trust-row-warning"
                                            type="button"
                                            :aria-pressed="selectedSymbol === row.symbol"
                                            @click="selectedSymbol = row.symbol"
                                        >
                                            <span class="trust-row-copy">
                                                <strong class="trust-row-symbol">
                                                    {{ formatTrustBoardSymbol(row.symbol) }}
                                                </strong>
                                                <small>{{ formatAutopilotReason(row.primary_reason_code, row.primary_reason_value) }}</small>
                                            </span>
                                            <span class="trust-row-meta">
                                                {{ formatAutopilotConfidenceBadge(row.confidence_bucket) }}
                                                · {{ row.trust_score.toFixed(1) }}
                                            </span>
                                        </button>
                                        <div
                                            v-if="!data.trust_board.cooling.length"
                                            class="trust-empty"
                                        >
                                            No cooling symbols in the latest snapshot.
                                        </div>
                                    </section>
                                </div>
                            </n-flex>
                        </n-card>

                        <n-card class="page-section-card mw-muted-card" content-style="padding: 18px 20px;">
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
                                        <div class="selected-metric">
                                            <span class="metric-label">Entry sizing</span>
                                            <strong>{{ formatAutopilotEntrySizingTitle(data) }}</strong>
                                        </div>
                                    </div>

                                    <div class="reason-list">
                                        <p>
                                            <strong>Entry sizing:</strong>
                                            {{ formatAutopilotEntrySizingBody(data) }}
                                        </p>
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

                    <n-card class="page-section-card mw-muted-card" content-style="padding: 18px 20px;">
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
                                    <p class="event-copy">{{ formatAutopilotEvent(event) }}</p>
                                    <small class="event-meta">
                                        {{ formatAutopilotTimestamp(event.created_at) }}
                                    </small>
                                </div>
                            </div>
                            <n-empty
                                v-else
                                description="Moonwalker has not recorded any Autopilot memory events yet."
                            />
                        </n-flex>
                    </n-card>
                </template>
            </n-flex>
        </n-card>
    </div>
</template>

<style scoped>
.autopilot-memory-page {
    display: flex;
    flex-direction: column;
    gap: 0;
}

.page-header {
    margin-bottom: 4px;
}

.autopilot-shell {
    width: 100%;
}

.page-copy {
    flex: 1 1 min(40rem, 100%);
    min-width: min(40rem, 100%);
    max-width: none;
}

.page-title {
    margin: 6px 0 8px;
    color: var(--mw-color-text-primary);
    font-family: var(--mw-font-display);
    font-size: 2rem;
    font-weight: 700;
    letter-spacing: -0.03em;
    white-space: nowrap;
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

.section-title,
.column-title {
    margin: 0 0 6px;
    color: var(--mw-color-text-primary);
    font-family: var(--mw-font-display);
    letter-spacing: -0.02em;
}

.page-section-card {
    height: auto;
    align-self: start;
}

.grid-shell {
    display: grid;
    gap: 16px;
    align-items: start;
    grid-template-columns: minmax(0, 1.3fr) minmax(0, 1fr);
}

.board-columns {
    display: grid;
    gap: 14px;
    grid-template-columns: repeat(2, minmax(0, 1fr));
}

.board-columns section {
    display: grid;
    gap: 10px;
    align-content: start;
    padding: 14px;
    border-radius: 12px;
    background: var(--mw-surface-card-subtle);
    border: 1px solid var(--mw-color-border-subtle, #d5dbd5);
}

.trust-row {
    width: 100%;
    padding: 11px 12px;
    border-radius: 10px;
    border: 1px solid var(--mw-color-border-subtle, #d5dbd5);
    background: var(--mw-surface-card-muted);
    color: var(--mw-color-text-primary);
    display: flex;
    justify-content: space-between;
    align-items: center;
    text-align: left;
    gap: 12px;
    cursor: pointer;
    transition:
        border-color 140ms ease,
        background-color 140ms ease,
    box-shadow 140ms ease,
    transform 140ms ease;
}

.trust-row:hover {
    box-shadow: 0 10px 20px rgba(24, 46, 38, 0.08);
    transform: translateY(-1px);
}

.trust-row:focus-visible {
    outline: 2px solid rgba(29, 92, 73, 0.45);
    outline-offset: 3px;
}

.trust-row[aria-pressed='true'] {
    background: #eef4ef;
    border-color: rgba(29, 92, 73, 0.32);
    box-shadow: inset 0 0 0 1px rgba(29, 92, 73, 0.08);
}

.trust-row strong,
.trust-row small {
    display: block;
}

.trust-row-copy {
    flex: 1 1 auto;
    min-width: 0;
}

.trust-row-symbol {
    color: var(--mw-color-text-primary);
    font-family: var(--mw-font-mono);
    font-size: 0.98rem;
    font-weight: 700;
    letter-spacing: 0.01em;
    line-height: 1.25;
}

.trust-row small {
    margin-top: 4px;
    color: var(--mw-color-text-secondary);
    font-family: var(--mw-font-body);
    font-size: 0.85rem;
    line-height: 1.45;
}

.trust-row-positive {
    background: rgba(46, 125, 91, 0.08);
    border-color: rgba(46, 125, 91, 0.22);
}

.trust-row-positive:hover {
    background: rgba(46, 125, 91, 0.12);
    border-color: rgba(46, 125, 91, 0.34);
}

.trust-row-warning {
    background: rgba(183, 121, 31, 0.08);
    border-color: rgba(183, 121, 31, 0.22);
}

.trust-row-warning:hover {
    background: rgba(183, 121, 31, 0.12);
    border-color: rgba(183, 121, 31, 0.34);
}

.trust-row-positive[aria-pressed='true'] {
    background: rgba(46, 125, 91, 0.15);
    border-color: rgba(46, 125, 91, 0.4);
}

.trust-row-warning[aria-pressed='true'] {
    background: rgba(183, 121, 31, 0.15);
    border-color: rgba(183, 121, 31, 0.4);
}

.trust-row-meta {
    flex: 0 0 auto;
    padding: 0.32rem 0.58rem;
    border-radius: 999px;
    border: 1px solid transparent;
    font-family: var(--mw-font-mono);
    font-size: 0.82rem;
    font-weight: 600;
    white-space: nowrap;
}

.trust-row-positive .trust-row-meta {
    background: rgba(46, 125, 91, 0.12);
    border-color: rgba(46, 125, 91, 0.18);
    color: var(--mw-color-primary);
}

.trust-row-warning .trust-row-meta {
    background: rgba(183, 121, 31, 0.12);
    border-color: rgba(183, 121, 31, 0.18);
    color: #8a5e15;
}

.trust-empty {
    min-height: 84px;
    padding: 0 2px;
    color: var(--mw-color-text-secondary);
    font-family: var(--mw-font-body);
    font-size: 0.9rem;
    line-height: 1.5;
    display: flex;
    align-items: center;
}

.selected-grid {
    display: grid;
    gap: 12px;
    grid-template-columns: repeat(2, minmax(0, 1fr));
}

.selected-metric {
    padding: 12px 14px;
    border-radius: 10px;
    background: var(--mw-surface-card-muted);
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
    padding: 10px 12px;
    border-radius: 10px;
    background: var(--mw-surface-card-muted);
    border: 1px solid var(--mw-color-border-subtle, #d5dbd5);
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 16px;
}

.event-copy {
    margin: 0;
    flex: 1 1 auto;
}

.event-meta {
    flex: 0 0 auto;
    color: var(--mw-color-text-secondary);
    font-family: var(--mw-font-mono);
    font-size: 0.78rem;
    white-space: nowrap;
}

@media (max-width: 900px) {
    .grid-shell,
    .board-columns,
    .selected-grid {
        grid-template-columns: 1fr;
    }

    .page-copy {
        min-width: 0;
    }

    .page-title {
        white-space: normal;
    }

    .page-actions {
        width: 100%;
    }

    .page-actions :deep(.n-button) {
        flex: 1 1 auto;
    }

    .event-row {
        align-items: flex-start;
        flex-direction: column;
        gap: 6px;
    }

    .trust-row {
        align-items: flex-start;
        flex-direction: column;
    }

    .event-meta {
        white-space: normal;
    }

    .trust-row-meta {
        white-space: normal;
    }
}
</style>
