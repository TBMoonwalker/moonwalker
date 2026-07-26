<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useWebSocketDataStore, type WebSocketStatus } from '../stores/websocket'

const openTradesStore = useWebSocketDataStore('openTrades')
const closedTradesStore = useWebSocketDataStore('closedTrades')
const unsellableTradesStore = useWebSocketDataStore('unsellableTrades')
const waitingCampaignsStore = useWebSocketDataStore('waitingCampaigns')
const statisticsStore = useWebSocketDataStore('statistics')

const openTradesState = storeToRefs(openTradesStore)
const closedTradesState = storeToRefs(closedTradesStore)
const unsellableTradesState = storeToRefs(unsellableTradesStore)
const waitingCampaignsState = storeToRefs(waitingCampaignsStore)
const statisticsState = storeToRefs(statisticsStore)
const now = ref(Date.now())
let refreshTimer: number | null = null

function getTagType(
  status: WebSocketStatus,
): 'default' | 'success' | 'warning' | 'error' {
  if (status === 'OPEN') {
    return 'success'
  }

  if (status === 'CONNECTING') {
    return 'warning'
  }

  return 'error'
}

function formatRelativeTime(timestamp: number | null): string {
  if (timestamp === null) {
    return 'Waiting for activity'
  }

  const deltaSeconds = Math.max(0, Math.floor((now.value - timestamp) / 1000))
  if (deltaSeconds < 5) {
    return 'Just now'
  }
  if (deltaSeconds < 60) {
    return `${deltaSeconds}s ago`
  }

  const deltaMinutes = Math.floor(deltaSeconds / 60)
  if (deltaMinutes < 60) {
    return `${deltaMinutes}m ago`
  }

  return new Date(timestamp).toLocaleTimeString()
}

const streamCards = computed(() => [
  {
    key: 'open',
    label: 'Open trades',
    description: 'Active positions and realtime deal updates.',
    status: openTradesState.status.value,
    tagType: getTagType(openTradesState.status.value),
    hasReceivedData: openTradesState.hasReceivedData.value,
    lastMessageLabel: formatRelativeTime(openTradesState.lastMessageAt.value),
    lastStatusLabel: formatRelativeTime(openTradesState.lastStatusAt.value),
    reconnectCount: openTradesState.reconnectCount.value,
  },
  {
    key: 'closed',
    label: 'Closed trades',
    description: 'Recently completed trade history updates.',
    status: closedTradesState.status.value,
    tagType: getTagType(closedTradesState.status.value),
    hasReceivedData: closedTradesState.hasReceivedData.value,
    lastMessageLabel: formatRelativeTime(closedTradesState.lastMessageAt.value),
    lastStatusLabel: formatRelativeTime(closedTradesState.lastStatusAt.value),
    reconnectCount: closedTradesState.reconnectCount.value,
  },
  {
    key: 'unsellable',
    label: 'Unsellable trades',
    description: 'Archived remainder positions and recovery tracking.',
    status: unsellableTradesState.status.value,
    tagType: getTagType(unsellableTradesState.status.value),
    hasReceivedData: unsellableTradesState.hasReceivedData.value,
    lastMessageLabel: formatRelativeTime(unsellableTradesState.lastMessageAt.value),
    lastStatusLabel: formatRelativeTime(unsellableTradesState.lastStatusAt.value),
    reconnectCount: unsellableTradesState.reconnectCount.value,
  },
  {
    key: 'waitingCampaigns',
    label: 'Waiting campaigns',
    description: 'Flat sidestep campaigns waiting for re-entry.',
    status: waitingCampaignsState.status.value,
    tagType: getTagType(waitingCampaignsState.status.value),
    hasReceivedData: waitingCampaignsState.hasReceivedData.value,
    lastMessageLabel: formatRelativeTime(waitingCampaignsState.lastMessageAt.value),
    lastStatusLabel: formatRelativeTime(waitingCampaignsState.lastStatusAt.value),
    reconnectCount: waitingCampaignsState.reconnectCount.value,
  },
  {
    key: 'statistics',
    label: 'Statistics',
    description: 'Portfolio profit, funds, and health metrics.',
    status: statisticsState.status.value,
    tagType: getTagType(statisticsState.status.value),
    hasReceivedData: statisticsState.hasReceivedData.value,
    lastMessageLabel: formatRelativeTime(statisticsState.lastMessageAt.value),
    lastStatusLabel: formatRelativeTime(statisticsState.lastStatusAt.value),
    reconnectCount: statisticsState.reconnectCount.value,
  },
])

onMounted(() => {
  refreshTimer = window.setInterval(() => {
    now.value = Date.now()
  }, 1000)
})

onUnmounted(() => {
  if (refreshTimer !== null) {
    window.clearInterval(refreshTimer)
  }
})
</script>

<template>
  <n-card
    class="stream-ledger dashboard-panel ledger-panel"
    content-style="padding: 0;"
    role="status"
    aria-live="polite"
    aria-atomic="true"
  >
    <div class="stream-ledger-header" aria-hidden="true">
      <span>Realtime stream</span>
      <span>Status</span>
      <span>Payload</span>
      <span>Last message</span>
      <span>Reconnects</span>
    </div>
    <div
      v-for="stream in streamCards"
      :key="stream.key"
      class="stream-row"
    >
      <div class="stream-heading">
        <n-text strong class="stream-title">{{ stream.label }}</n-text>
        <n-text depth="3" class="stream-description">{{ stream.description }}</n-text>
      </div>
      <n-tag :type="stream.tagType" size="small">
        {{ stream.status }}
      </n-tag>
      <div class="stream-stat">
        <n-text>{{ stream.hasReceivedData ? 'Receiving data' : 'Waiting for first payload' }}</n-text>
      </div>
      <div class="stream-stat">
        <n-text>{{ stream.lastMessageLabel }}</n-text>
        <n-text depth="3">{{ stream.lastStatusLabel }}</n-text>
      </div>
      <div class="stream-stat">
        <n-text>{{ stream.reconnectCount }}</n-text>
      </div>
    </div>
  </n-card>
</template>

<style scoped>
.stream-ledger {
  width: 100%;
}

.stream-ledger-header,
.stream-row {
  display: grid;
  grid-template-columns: minmax(220px, 1.4fr) 108px minmax(160px, 1fr) minmax(150px, 1fr) 96px;
  gap: 12px;
  align-items: center;
}

.stream-ledger-header {
  min-height: 44px;
  padding: 0 16px;
  border-bottom: 1px solid var(--mw-color-border);
  color: var(--mw-color-text-muted);
  font-size: 12px;
  font-weight: 500;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.stream-row {
  min-height: 66px;
  padding: 10px 16px;
  border-bottom: 1px solid rgba(213, 219, 213, 0.7);
}

.stream-row:last-child {
  border-bottom: 0;
}

.stream-row:hover {
  background: var(--mw-surface-card-muted);
}

.stream-heading {
  min-width: 0;
}

.stream-title {
  display: block;
  color: var(--mw-color-text-primary);
  font-family: var(--mw-font-mono);
  font-size: 0.95rem;
  font-weight: 600;
}

.stream-description {
  display: block;
  margin-top: 3px;
  font-size: 0.9rem;
  line-height: 1.35;
}

.stream-stat {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 3px;
  font-family: var(--mw-font-mono);
  font-size: 0.9rem;
  font-variant-numeric: tabular-nums;
}

@media (max-width: 900px) {
  .stream-ledger-header {
    display: none;
  }

  .stream-row {
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 8px 12px;
  }

  .stream-stat {
    grid-column: 1 / -1;
  }
}
</style>
