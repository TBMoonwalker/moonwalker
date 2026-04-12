<script setup lang="ts">
import { computed } from 'vue'
import { storeToRefs } from 'pinia'

import { useWebSocketDataStore } from '../../stores/websocket'
import type { WebSocketStatus } from '../../stores/websocket'

interface StreamSummary {
    key: string
    label: string
    status: WebSocketStatus
    hasReceivedData: boolean
    reconnectCount: number
}

const emit = defineEmits<{
    'open-monitoring': []
}>()

const openTradesStore = useWebSocketDataStore('openTrades')
const closedTradesStore = useWebSocketDataStore('closedTrades')
const unsellableTradesStore = useWebSocketDataStore('unsellableTrades')
const statisticsStore = useWebSocketDataStore('statistics')

const openTradesState = storeToRefs(openTradesStore)
const closedTradesState = storeToRefs(closedTradesStore)
const unsellableTradesState = storeToRefs(unsellableTradesStore)
const statisticsState = storeToRefs(statisticsStore)

const streams = computed<StreamSummary[]>(() => [
    {
        key: 'open',
        label: 'Open trades',
        status: openTradesState.status.value,
        hasReceivedData: openTradesState.hasReceivedData.value,
        reconnectCount: openTradesState.reconnectCount.value,
    },
    {
        key: 'closed',
        label: 'Closed trades',
        status: closedTradesState.status.value,
        hasReceivedData: closedTradesState.hasReceivedData.value,
        reconnectCount: closedTradesState.reconnectCount.value,
    },
    {
        key: 'unsellable',
        label: 'Unsellable trades',
        status: unsellableTradesState.status.value,
        hasReceivedData: unsellableTradesState.hasReceivedData.value,
        reconnectCount: unsellableTradesState.reconnectCount.value,
    },
    {
        key: 'statistics',
        label: 'Statistics',
        status: statisticsState.status.value,
        hasReceivedData: statisticsState.hasReceivedData.value,
        reconnectCount: statisticsState.reconnectCount.value,
    },
])

const openCount = computed(
    () => streams.value.filter((stream) => stream.status === 'OPEN').length,
)
const receivingCount = computed(
    () =>
        streams.value.filter(
            (stream) => stream.status === 'OPEN' && stream.hasReceivedData,
        ).length,
)
const totalReconnects = computed(() =>
    streams.value.reduce((total, stream) => total + stream.reconnectCount, 0),
)

const closedStream = computed(
    () => streams.value.find((stream) => stream.status === 'CLOSED') ?? null,
)
const connectingStream = computed(
    () =>
        streams.value.find((stream) => stream.status === 'CONNECTING') ?? null,
)
const waitingStream = computed(
    () =>
        streams.value.find(
            (stream) => stream.status === 'OPEN' && !stream.hasReceivedData,
        ) ?? null,
)

const statusTitle = computed(() => {
    if (closedStream.value) {
        return 'Monitoring needs attention'
    }
    if (connectingStream.value) {
        return 'Monitoring is reconnecting'
    }
    if (waitingStream.value) {
        return 'Monitoring is warming up'
    }
    return 'Monitoring is healthy'
})

const statusBody = computed(() => {
    if (closedStream.value) {
        return `${closedStream.value.label} stream is currently offline.`
    }
    if (connectingStream.value) {
        return `${connectingStream.value.label} stream is reconnecting while Moonwalker keeps watch.`
    }
    if (waitingStream.value) {
        return `${waitingStream.value.label} stream is open, but it is still waiting for the first payload.`
    }
    return 'Moonwalker is receiving live updates across all tracked streams.'
})

const alertTitle = computed(() => {
    if (closedStream.value) {
        return 'Stream health needs attention'
    }
    if (connectingStream.value) {
        return 'Realtime streams are reconnecting'
    }
    if (waitingStream.value) {
        return 'Streams are still warming up'
    }
    return null
})

const alertType = computed(() => {
    if (closedStream.value) {
        return 'warning'
    }
    return 'info'
})

const featuredInsight = computed(() => {
    if (closedStream.value) {
        return `${closedStream.value.label} is down, so the full Monitoring page should be your next stop.`
    }
    if (connectingStream.value) {
        return `${connectingStream.value.label} is reconnecting, but the rest of the cockpit can keep running.`
    }
    if (waitingStream.value) {
        return `${waitingStream.value.label} is the only stream still waiting for its first payload.`
    }
    return 'All four realtime streams are open and receiving data.'
})
</script>

<template>
    <n-card class="monitoring-preview" content-style="padding: 18px 20px;">
        <n-flex vertical :size="14">
            <n-flex justify="space-between" align="start" :wrap="true" :size="[12, 12]">
                <div class="preview-copy">
                    <h2 class="preview-title">{{ statusTitle }}</h2>
                    <n-text depth="3">{{ statusBody }}</n-text>
                </div>
                <div class="preview-actions">
                    <n-button secondary @click="emit('open-monitoring')">
                        Open Monitoring
                    </n-button>
                </div>
            </n-flex>

            <n-alert
                v-if="alertTitle"
                :type="alertType"
                :bordered="false"
                :title="alertTitle"
            >
                {{ statusBody }}
            </n-alert>

            <div class="hero-insight">
                <p class="hero-insight-copy">{{ featuredInsight }}</p>
                <p class="hero-insight-meta">
                    {{ receivingCount }} of {{ streams.length }} streams receiving payloads
                </p>
            </div>

            <div class="preview-metrics">
                <div class="metric-chip">
                    <span class="metric-label">Open streams</span>
                    <strong class="metric-value">
                        {{ openCount }}/{{ streams.length }}
                    </strong>
                </div>
                <div class="metric-chip">
                    <span class="metric-label">Receiving payloads</span>
                    <strong class="metric-value">
                        {{ receivingCount }}/{{ streams.length }}
                    </strong>
                </div>
                <div class="metric-chip">
                    <span class="metric-label">Reconnects</span>
                    <strong class="metric-value">{{ totalReconnects }}</strong>
                </div>
            </div>
        </n-flex>
    </n-card>
</template>

<style scoped>
.monitoring-preview {
    width: 100%;
    min-height: 100%;
    border-color: rgba(29, 92, 73, 0.14);
    background: var(--mw-surface-shell);
    box-shadow: var(--mw-shadow-card);
    color: var(--mw-color-text-primary);
}

.preview-title {
    margin: 6px 0 4px;
    color: var(--mw-color-text-primary);
    font-family: var(--mw-font-display);
    font-size: 1.35rem;
    font-weight: 700;
    letter-spacing: -0.02em;
}

.preview-copy {
    max-width: 58ch;
}

.preview-actions {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
}

.hero-insight {
    padding: 14px 16px;
    border-radius: 10px;
    background: var(--mw-surface-card-subtle);
    border: 1px solid rgba(29, 92, 73, 0.1);
}

.hero-insight-copy {
    margin: 0 0 6px;
    color: var(--mw-color-text-primary);
    font-family: var(--mw-font-display);
    font-size: 1.1rem;
    font-weight: 600;
    letter-spacing: -0.015em;
}

.hero-insight-meta {
    margin: 0;
    color: var(--mw-color-text-secondary);
    font-family: var(--mw-font-body);
    font-size: 0.95rem;
}

.preview-metrics {
    display: grid;
    gap: 12px;
    grid-template-columns: repeat(3, minmax(0, 1fr));
}

.metric-chip {
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

.metric-value {
    color: var(--mw-color-text-primary);
    font-family: var(--mw-font-mono);
    font-size: 1rem;
}

@media (max-width: 768px) {
    .preview-actions {
        width: 100%;
    }

    .preview-actions :deep(.n-button) {
        flex: 1 1 auto;
    }

    .preview-metrics {
        grid-template-columns: 1fr;
    }
}
</style>
