<script setup lang="ts">
import { MOONWALKER_API_PORT, MOONWALKER_API_HOST } from './config'
import { RouterView } from 'vue-router'
import { useOsTheme, darkTheme } from 'naive-ui'
import { computed, watch } from 'vue'
import { useWebSocketDataStore } from './stores/websocket'
import { useWebSocket } from '@vueuse/core'

const osThemeRef = useOsTheme()
const theme = computed(() => (osThemeRef.value === 'dark' ? darkTheme : null))

// Stores
const open_trade_store = useWebSocketDataStore("openTrades")
const closed_trade_store = useWebSocketDataStore("closedTrades")
const statistics_store = useWebSocketDataStore("statistics")

const closed_orders = useWebSocket('ws://' + MOONWALKER_API_HOST + ':' + MOONWALKER_API_PORT + '/trades/closed', {
  autoReconnect: true,
})

const open_orders = useWebSocket('ws://' + MOONWALKER_API_HOST + ':' + MOONWALKER_API_PORT + '/trades/open', {
  autoReconnect: true,
})

const statistics = useWebSocket('ws://' + MOONWALKER_API_HOST + ':' + MOONWALKER_API_PORT + '/statistic/profit', {
  autoReconnect: true,
})

// Watch Stores
watch(open_orders.data, async (newData) => {
  open_trade_store.json = newData
})

watch(closed_orders.data, async (newData) => {
  closed_trade_store.json = newData
})

watch(statistics.data, async (newData) => {
  statistics_store.json = newData
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