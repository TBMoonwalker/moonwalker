<script setup lang="ts">
import { MOONWALKER_API_PORT, MOONWALKER_API_HOST } from './config'
import { RouterView } from 'vue-router'
import { darkTheme, NConfigProvider, NDialogProvider, NFlex, NGlobalStyle, NMessageProvider, NModalProvider, NNotificationProvider, useOsTheme } from 'naive-ui'
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useWebSocketDataStore } from './stores/websocket'
import { useWebSocket } from '@vueuse/core'
import axios from 'axios'

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
    const response = await axios.get(`http://${MOONWALKER_API_HOST}:${MOONWALKER_API_PORT}/config/all`)
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
  onData: (payload: string | null) => void,
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
      onData((event.data as string) ?? null)
    },
    onConnected() {
      lastMessageAt.value = Date.now()
    },
  })

  const lastMessageAt = ref(Date.now())
  let lastReconnectAt = 0

  const reconnect = () => {
    if (!wsWatchdogEnabled.value) {
      return
    }
    const now = Date.now()
    if (now - lastReconnectAt < wsReconnectDebounceMs.value) {
      return
    }
    lastReconnectAt = now
    socket.close()
    setTimeout(() => socket.open(), 250)
    console.debug(`[ws] reinitialized ${name}`)
  }

  watch(socket.status, (status) => {
    if (status === 'OPEN') {
      lastMessageAt.value = Date.now()
    }
  })

  const onActiveAgain = () => {
    if (!wsWatchdogEnabled.value) {
      return
    }
    if (!document.hidden && navigator.onLine) {
      reconnect()
    }
  }

  let healthcheckTimer: number | null = null
  const runHealthcheck = () => {
    if (
      healthcheckEnabled &&
      wsWatchdogEnabled.value &&
      !document.hidden &&
      navigator.onLine &&
      socket.status.value === 'OPEN' &&
      Date.now() - lastMessageAt.value > wsStaleTimeoutMs.value
    ) {
      reconnect()
    }
    healthcheckTimer = window.setTimeout(runHealthcheck, wsHealthcheckIntervalMs.value)
  }
  runHealthcheck()

  const visibilityHandler = () => {
    if (!document.hidden) {
      onActiveAgain()
    }
  }

  window.addEventListener('focus', onActiveAgain)
  window.addEventListener('online', onActiveAgain)
  document.addEventListener('visibilitychange', visibilityHandler)

  return () => {
    if (healthcheckTimer !== null) {
      window.clearTimeout(healthcheckTimer)
    }
    window.removeEventListener('focus', onActiveAgain)
    window.removeEventListener('online', onActiveAgain)
    document.removeEventListener('visibilitychange', visibilityHandler)
    socket.close()
  }
}

const disposeOpenOrders = createManagedSocket(
  'openTrades',
  buildWsUrl('/trades/open'),
  (payload) => open_trade_store.setRaw(payload),
  { healthcheck: false },
)
const disposeClosedOrders = createManagedSocket(
  'closedTrades',
  buildWsUrl('/trades/closed'),
  (payload) => closed_trade_store.setRaw(payload),
  { healthcheck: false },
)
const disposeStatistics = createManagedSocket(
  'statistics',
  buildWsUrl('/statistic/profit'),
  (payload) => statistics_store.setRaw(payload),
)

onUnmounted(() => {
  disposeOpenOrders()
  disposeClosedOrders()
  disposeStatistics()
})

onMounted(() => {
  loadWsWatchdogConfig()
})
</script>

<template>
  <n-config-provider :theme="theme">
    <n-global-style />
    <n-message-provider>
      <n-notification-provider>
        <n-modal-provider>
          <n-dialog-provider>
            <n-flex justify="center">
              <RouterView />
            </n-flex>
          </n-dialog-provider>
        </n-modal-provider>
      </n-notification-provider>
    </n-message-provider>
  </n-config-provider>
</template>
