<script setup lang="ts">
import { MOONWALKER_API_ORIGIN } from './config'
import { RouterView } from 'vue-router'
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useWebSocketDataStore } from './stores/websocket'
import { useWebSocket } from '@vueuse/core'
import AppHeader from './components/AppHeader.vue'
import { useSharedConfigSnapshot } from './control-center/configSnapshotStore'
import { trackUiEvent } from './utils/uiTelemetry'
import type { WebSocketStatus } from './stores/websocket'
import { NConfigProvider } from 'naive-ui/es/config-provider'
import { NDialogProvider } from 'naive-ui/es/dialog'
import { NGlobalStyle } from 'naive-ui/es/global-style'
import { NMessageProvider } from 'naive-ui/es/message'
import { NModalProvider } from 'naive-ui/es/modal'
import { NNotificationProvider } from 'naive-ui/es/notification'
import { darkTheme } from 'naive-ui/es/themes'
import { useOsTheme } from 'vooks'

const DEFAULT_WS_WATCHDOG_ENABLED = false
const DEFAULT_WS_HEALTHCHECK_INTERVAL_MS = 5000
const DEFAULT_WS_STALE_TIMEOUT_MS = 20000
const DEFAULT_WS_RECONNECT_DEBOUNCE_MS = 2000

const osThemeRef = useOsTheme()
const theme = computed(() => (osThemeRef.value === 'dark' ? darkTheme : null))

// Stores
const open_trade_store = useWebSocketDataStore("openTrades")
const closed_trade_store = useWebSocketDataStore("closedTrades")
const unsellable_trade_store = useWebSocketDataStore("unsellableTrades")
const statistics_store = useWebSocketDataStore("statistics")
const wsWatchdogEnabled = ref(DEFAULT_WS_WATCHDOG_ENABLED)
const wsHealthcheckIntervalMs = ref(DEFAULT_WS_HEALTHCHECK_INTERVAL_MS)
const wsStaleTimeoutMs = ref(DEFAULT_WS_STALE_TIMEOUT_MS)
const wsReconnectDebounceMs = ref(DEFAULT_WS_RECONNECT_DEBOUNCE_MS)
const configSnapshotStore = useSharedConfigSnapshot()

const buildWsUrl = (path: string): string => {
  const url = new URL(path, MOONWALKER_API_ORIGIN)
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  return url.toString()
}

const toNumberOrDefault = (value: unknown, fallback: number): number => {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

const toBooleanOrDefault = (value: unknown, fallback: boolean): boolean => {
  if (typeof value === 'boolean') {
    return value
  }
  if (typeof value === 'string') {
    const normalized = value.trim().toLowerCase()
    if (['true', '1', 'yes', 'on'].includes(normalized)) {
      return true
    }
    if (['false', '0', 'no', 'off'].includes(normalized)) {
      return false
    }
  }
  return fallback
}

const applyWsWatchdogConfig = (config: Record<string, unknown> | null) => {
  wsWatchdogEnabled.value = toBooleanOrDefault(
    config?.ws_watchdog_enabled,
    DEFAULT_WS_WATCHDOG_ENABLED,
  )
  wsHealthcheckIntervalMs.value = Math.max(
    1000,
    toNumberOrDefault(
      config?.ws_healthcheck_interval_ms,
      DEFAULT_WS_HEALTHCHECK_INTERVAL_MS,
    ),
  )
  wsStaleTimeoutMs.value = Math.max(
    5000,
    toNumberOrDefault(
      config?.ws_stale_timeout_ms,
      DEFAULT_WS_STALE_TIMEOUT_MS,
    ),
  )
  wsReconnectDebounceMs.value = Math.max(
    500,
    toNumberOrDefault(
      config?.ws_reconnect_debounce_ms,
      DEFAULT_WS_RECONNECT_DEBOUNCE_MS,
    ),
  )
}

const createManagedSocket = (
  name: string,
  url: string,
  store: ReturnType<typeof useWebSocketDataStore>,
  options?: { healthcheck?: boolean },
) => {
  const healthcheckEnabled = options?.healthcheck ?? true
  const socket = useWebSocket(url, {
    autoReconnect: {
      retries: -1,
      delay: 1500,
    },
    onMessage(_ws, event) {
      lastMessageAt.value = Date.now()
      store.setRaw((event.data as string) ?? null)
    },
  })

  const lastMessageAt = ref(Date.now())
  let lastReconnectAt = 0

  const reconnect = (reason: string) => {
    if (!wsWatchdogEnabled.value) {
      return
    }
    const now = Date.now()
    if (now - lastReconnectAt < wsReconnectDebounceMs.value) {
      trackUiEvent('ws_reconnect_debounced', { socket: name, reason })
      return
    }
    lastReconnectAt = now
    store.markReconnect()
    trackUiEvent('ws_reconnect', { socket: name, reason })
    socket.close()
    setTimeout(() => socket.open(), 250)
    console.debug(`[ws] reinitialized ${name}`)
  }

  const stopStatusWatch = watch(socket.status, (status) => {
    store.setStatus(status as WebSocketStatus)
    if (status === 'OPEN') {
      lastMessageAt.value = Date.now()
    }
  }, { immediate: true })

  const dispose = () => {
    stopStatusWatch()
    store.setStatus('CLOSED')
    socket.close()
  }

  return {
    name,
    socket,
    healthcheckEnabled,
    lastMessageAt,
    reconnect,
    dispose,
  }
}

const managedSockets = [
  createManagedSocket(
  'openTrades',
  buildWsUrl('/trades/open'),
  open_trade_store,
  ),
  createManagedSocket(
  'closedTrades',
  buildWsUrl('/trades/closed'),
  closed_trade_store,
  ),
  createManagedSocket(
  'unsellableTrades',
  buildWsUrl('/trades/unsellable'),
  unsellable_trade_store,
  ),
  createManagedSocket(
  'statistics',
  buildWsUrl('/statistic/profit'),
  statistics_store,
  ),
]

const onActiveAgain = () => {
  if (!wsWatchdogEnabled.value) {
    return
  }
  if (document.hidden || !navigator.onLine) {
    return
  }
  for (const managedSocket of managedSockets) {
    if (managedSocket.socket.status.value !== 'OPEN') {
      managedSocket.reconnect('app_active')
    }
  }
}

const visibilityHandler = () => {
  if (!document.hidden) {
    onActiveAgain()
  }
}

let healthcheckTimer: number | null = null
const runHealthcheck = () => {
  if (wsWatchdogEnabled.value && !document.hidden && navigator.onLine) {
    const now = Date.now()
    for (const managedSocket of managedSockets) {
      if (
        managedSocket.healthcheckEnabled &&
        managedSocket.socket.status.value === 'OPEN' &&
        now - managedSocket.lastMessageAt.value > wsStaleTimeoutMs.value
      ) {
        managedSocket.reconnect('stale_timeout')
      }
    }
  }
  healthcheckTimer = window.setTimeout(runHealthcheck, wsHealthcheckIntervalMs.value)
}

onUnmounted(() => {
  if (healthcheckTimer !== null) {
    window.clearTimeout(healthcheckTimer)
  }
  window.removeEventListener('focus', onActiveAgain)
  window.removeEventListener('online', onActiveAgain)
  document.removeEventListener('visibilitychange', visibilityHandler)
  for (const managedSocket of managedSockets) {
    managedSocket.dispose()
  }
})

onMounted(() => {
  void configSnapshotStore.ensureLoaded(false).catch((error) => {
    console.debug('[ws] using default watchdog config', error)
  })
  runHealthcheck()
  window.addEventListener('focus', onActiveAgain)
  window.addEventListener('online', onActiveAgain)
  document.addEventListener('visibilitychange', visibilityHandler)
})

watch(
  () => configSnapshotStore.snapshot.value,
  (nextSnapshot) => {
    applyWsWatchdogConfig(nextSnapshot)
  },
  { immediate: true },
)
</script>

<template>
  <n-config-provider :theme="theme">
    <n-global-style />
    <n-message-provider>
      <n-notification-provider>
        <n-modal-provider>
          <n-dialog-provider>
            <div class="app-layout">
              <AppHeader />
              <main class="app-content">
                <RouterView />
              </main>
            </div>
          </n-dialog-provider>
        </n-modal-provider>
      </n-notification-provider>
    </n-message-provider>
  </n-config-provider>
</template>

<style scoped>
.app-layout {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.app-content {
  width: 100%;
  max-width: 1600px;
  margin: 0 auto;
}
</style>
