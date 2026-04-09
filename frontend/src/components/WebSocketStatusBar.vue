<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useWebSocketDataStore, type WebSocketStatus } from '../stores/websocket'

const openTradesStore = useWebSocketDataStore('openTrades')
const closedTradesStore = useWebSocketDataStore('closedTrades')
const unsellableTradesStore = useWebSocketDataStore('unsellableTrades')
const statisticsStore = useWebSocketDataStore('statistics')

const openTradesState = storeToRefs(openTradesStore)
const closedTradesState = storeToRefs(closedTradesStore)
const unsellableTradesState = storeToRefs(unsellableTradesStore)
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
  <div
    class="stream-card-grid"
    role="status"
    aria-live="polite"
    aria-atomic="true"
  >
    <n-card
      v-for="stream in streamCards"
      :key="stream.key"
      size="small"
      class="stream-card mw-muted-card"
      content-style="padding: 16px;"
    >
      <n-flex vertical :size="16">
        <n-flex justify="space-between" align="start" :wrap="false" :size="12">
          <n-flex vertical :size="4" class="stream-heading">
            <n-text depth="3" class="stream-kicker">Realtime stream</n-text>
            <n-text strong class="stream-title">{{ stream.label }}</n-text>
            <n-text depth="3">{{ stream.description }}</n-text>
          </n-flex>
          <n-tag :type="stream.tagType" size="medium">
            {{ stream.status }}
          </n-tag>
        </n-flex>
        <div class="stream-stats">
          <div class="stream-stat">
            <n-text depth="3">Payload</n-text>
            <n-text>{{ stream.hasReceivedData ? 'Receiving data' : 'Waiting for first payload' }}</n-text>
          </div>
          <div class="stream-stat">
            <n-text depth="3">Last message</n-text>
            <n-text>{{ stream.lastMessageLabel }}</n-text>
          </div>
          <div class="stream-stat">
            <n-text depth="3">Last status change</n-text>
            <n-text>{{ stream.lastStatusLabel }}</n-text>
          </div>
          <div class="stream-stat">
            <n-text depth="3">Reconnects</n-text>
            <n-text>{{ stream.reconnectCount }}</n-text>
          </div>
        </div>
      </n-flex>
    </n-card>
  </div>
</template>

<style scoped>
.stream-card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 12px;
}

.stream-card {
  min-height: 100%;
}

.stream-heading {
  min-width: 0;
}

.stream-kicker {
  font-size: 0.76rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.stream-title {
  font-size: 1rem;
}

.stream-stats {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.stream-stat {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

@media (max-width: 768px) {
  .stream-card-grid {
    grid-template-columns: 1fr;
  }

  .stream-stats {
    grid-template-columns: 1fr;
  }
}
</style>
