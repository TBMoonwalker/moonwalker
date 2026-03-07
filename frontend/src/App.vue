<script setup lang="ts">
import { MOONWALKER_API_PORT, MOONWALKER_API_HOST } from './config'
import { RouterView } from 'vue-router'
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useWebSocketDataStore } from './stores/websocket'
import { useWebSocket } from '@vueuse/core'
import {
  darkTheme,
  NConfigProvider,
  NDialogProvider,
  NGlobalStyle,
  NMessageProvider,
  NModalProvider,
  NNotificationProvider,
  useOsTheme
} from 'naive-ui'
import axios from 'axios'
import { trackUiEvent } from './utils/uiTelemetry'
import type { WebSocketStatus } from './stores/websocket'

const DEFAULT_WS_WATCHDOG_ENABLED = false
const DEFAULT_WS_HEALTHCHECK_INTERVAL_MS = 5000
const DEFAULT_WS_STALE_TIMEOUT_MS = 20000
const DEFAULT_WS_RECONNECT_DEBOUNCE_MS = 2000

const osThemeRef = useOsTheme()
const theme = computed(() => (osThemeRef.value === 'dark' ? darkTheme : null))

// Stores
const open_trade_store = useWebSocketDataStore("openTrades")
const closed_trade_store = useWebSocketDataStore("closedTrades")
const statistics_store = useWebSocketDataStore("statistics")
const wsWatchdogEnabled = ref(DEFAULT_WS_WATCHDOG_ENABLED)
const wsHealthcheckIntervalMs = ref(DEFAULT_WS_HEALTHCHECK_INTERVAL_MS)
const wsStaleTimeoutMs = ref(DEFAULT_WS_STALE_TIMEOUT_MS)
const wsReconnectDebounceMs = ref(DEFAULT_WS_RECONNECT_DEBOUNCE_MS)

const wsProtocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
const buildWsUrl = (path: string): string =>
  `${wsProtocol}://${MOONWALKER_API_HOST}:${MOONWALKER_API_PORT}${path}`
const buildHttpUrl = (path: string): string =>
  `${window.location.protocol}//${MOONWALKER_API_HOST}:${MOONWALKER_API_PORT}${path}`

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

const loadWsWatchdogConfig = async () => {
  try {
    const response = await axios.get(buildHttpUrl('/config/all'))
    wsWatchdogEnabled.value = toBooleanOrDefault(
      response.data?.ws_watchdog_enabled,
      DEFAULT_WS_WATCHDOG_ENABLED,
    )
    wsHealthcheckIntervalMs.value = Math.max(
      1000,
      toNumberOrDefault(
        response.data?.ws_healthcheck_interval_ms,
        DEFAULT_WS_HEALTHCHECK_INTERVAL_MS,
      ),
    )
    wsStaleTimeoutMs.value = Math.max(
      5000,
      toNumberOrDefault(
        response.data?.ws_stale_timeout_ms,
        DEFAULT_WS_STALE_TIMEOUT_MS,
      ),
    )
    wsReconnectDebounceMs.value = Math.max(
      500,
      toNumberOrDefault(
        response.data?.ws_reconnect_debounce_ms,
        DEFAULT_WS_RECONNECT_DEBOUNCE_MS,
      ),
    )
  } catch (error) {
    console.debug('[ws] using default watchdog config', error)
  }
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
  { healthcheck: false },
  ),
  createManagedSocket(
  'closedTrades',
  buildWsUrl('/trades/closed'),
  closed_trade_store,
  { healthcheck: false },
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
  loadWsWatchdogConfig()
  runHealthcheck()
  window.addEventListener('focus', onActiveAgain)
  window.addEventListener('online', onActiveAgain)
  document.addEventListener('visibilitychange', visibilityHandler)
})
</script>

<template>
  <n-config-provider :theme="theme">
    <n-global-style />
    <n-message-provider>
      <n-notification-provider>
        <n-modal-provider>
          <n-dialog-provider>
            <div class="app-layout">
              <RouterView />
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
}
</style>
