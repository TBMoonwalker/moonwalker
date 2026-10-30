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
import { storeToRefs } from 'pinia'
import { darkTheme } from 'naive-ui/es/themes'
import { themeTokens } from './theme/tokens'
import { useThemeStore } from './theme/themeStore'

const DEFAULT_WS_WATCHDOG_ENABLED = false
const DEFAULT_WS_HEALTHCHECK_INTERVAL_MS = 5000
const DEFAULT_WS_STALE_TIMEOUT_MS = 20000
const DEFAULT_WS_RECONNECT_DEBOUNCE_MS = 2000

const themeStore = useThemeStore()
const { scheme } = storeToRefs(themeStore)
const theme = computed(() => (scheme.value === "dark" ? darkTheme : null))
const themeOverrides = computed(() => themeTokens[scheme.value].naive)

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
let configRefreshTimer: number | undefined
let checkingConfig = false
const refreshSharedConfig = async () => {
  if (checkingConfig || document.hidden || !navigator.onLine) return
  checkingConfig = true
  try {
    if (!configSnapshotStore.snapshot.value) {
      await configSnapshotStore.ensureLoaded()
      return
    }
    const freshness = await configSnapshotStore.checkFreshness()
    if (freshness.status === 'stale') await configSnapshotStore.refresh()
  } catch {
    // Keep the last known snapshot until connectivity returns.
  } finally {
    checkingConfig = false
  }
}

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
  options?: { healthcheck?: boolean; recovery?: boolean },
) => {
  const healthcheckEnabled = options?.healthcheck ?? true
  const socketUrl = new URL(url)
  if (options?.recovery) socketUrl.searchParams.set('recovery', 'true')
  const socket = useWebSocket(socketUrl.toString(), {
    immediate: false,
    autoConnect: false,
    autoReconnect: {
      retries: -1,
      delay: 1500,
    },
    onMessage(ws, event) {
      if (document.hidden || ws !== socket.ws.value) return
      lastMessageAt.value = Date.now()
      const payload = (event.data as string) ?? null
      let valid = false
      try {
        const parsed: unknown = JSON.parse(payload)
        valid = name === 'openTrades' ? Array.isArray(parsed)
          : name === 'statistics' ? !!parsed && typeof parsed === 'object' &&
            typeof (parsed as Record<string, unknown>).funds_available === 'number' &&
            Number.isFinite((parsed as Record<string, number>).funds_available)
          : true
      } catch { /* Invalid payloads never certify freshness. */ }
      store.setRaw(payload, valid && !!options?.recovery)
    },
  })

  const lastMessageAt = ref(Date.now())
  let lastReconnectAt = 0
  let reconnectTimer: ReturnType<typeof setTimeout> | undefined

  const suspend = () => {
    if (reconnectTimer) clearTimeout(reconnectTimer)
    reconnectTimer = undefined
    store.invalidate()
    socket.close()
  }
  const resume = () => {
    if (document.hidden || !navigator.onLine || socket.status.value !== 'CLOSED') return
    socket.open()
  }

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
    suspend()
    reconnectTimer = setTimeout(resume, 250)
    console.debug(`[ws] reinitialized ${name}`)
  }

  const stopStatusWatch = watch(socket.status, (status) => {
    store.setStatus(status as WebSocketStatus)
    if (status === 'CLOSED') store.invalidate()
    if (status === 'OPEN') {
      lastMessageAt.value = Date.now()
    }
  }, { immediate: true })

  const dispose = () => {
    stopStatusWatch()
    store.setStatus('CLOSED')
    suspend()
  }

  return {
    name,
    socket,
    healthcheckEnabled,
    store,
    lastMessageAt,
    reconnect,
    suspend,
    resume,
    dispose,
  }
}

const managedSockets = [
  createManagedSocket(
  'openTrades',
  buildWsUrl('/trades/open'),
  open_trade_store,
  { recovery: true },
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
  { recovery: true },
   ),
]

const onActiveAgain = () => {
  void refreshSharedConfig()
  if (document.hidden || !navigator.onLine) {
    return
  }
  for (const managedSocket of managedSockets) {
    if (managedSocket.socket.status.value !== 'OPEN') {
      managedSocket.resume()
    }
  }
}

let pageHidden = document.hidden
const visibilityHandler = () => {
  if (pageHidden === document.hidden) return
  pageHidden = document.hidden
  if (pageHidden) managedSockets.forEach((socket) => socket.suspend())
  else onActiveAgain()
}
const onOffline = () => managedSockets.forEach((socket) => socket.suspend())

let healthcheckTimer: number | null = null
const runHealthcheck = () => {
  if (!document.hidden) {
    const now = Date.now()
    for (const managedSocket of managedSockets) {
      if (managedSocket.store.fresh && now - managedSocket.lastMessageAt.value > wsStaleTimeoutMs.value) {
        managedSocket.store.invalidate()
      }
    }
  }
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
  if (configRefreshTimer !== undefined) window.clearInterval(configRefreshTimer)
  if (healthcheckTimer !== null) {
    window.clearTimeout(healthcheckTimer)
  }
  window.removeEventListener('focus', onActiveAgain)
  window.removeEventListener('online', onActiveAgain)
  window.removeEventListener('offline', onOffline)
  document.removeEventListener('visibilitychange', visibilityHandler)
  for (const managedSocket of managedSockets) {
    managedSocket.dispose()
  }
})

onMounted(() => {
  onActiveAgain()
  void configSnapshotStore.ensureLoaded(false).catch((error) => {
    console.debug('[ws] using default watchdog config', error)
  })
  runHealthcheck()
  configRefreshTimer = window.setInterval(() => { void refreshSharedConfig() }, 15000)
  window.addEventListener('focus', onActiveAgain)
  window.addEventListener('online', onActiveAgain)
  window.addEventListener('offline', onOffline)
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
  <n-config-provider :theme="theme" :theme-overrides="themeOverrides">
    <n-global-style />
    <n-message-provider>
      <n-notification-provider>
        <n-modal-provider>
          <n-dialog-provider>
            <div class="app-layout">
              <AppHeader />
              <main class="app-content">
                <RouterView v-slot="{ Component, route }">
                  <component
                    :is="Component"
                    v-if="route.name === 'controlCenter'"
                  />
                  <KeepAlive v-else>
                    <component :is="Component" />
                  </KeepAlive>
                </RouterView>
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
  min-height: 100vh;
  display: grid;
  grid-template-columns: 224px minmax(0, 1fr);
  grid-template-rows: 64px minmax(0, 1fr);
}

.app-content {
  width: 100%;
  min-width: 0;
  grid-column: 2;
  grid-row: 2;
}

@media (max-width: 820px) {
  .app-layout {
    display: flex;
    flex-direction: column;
  }
}
</style>
