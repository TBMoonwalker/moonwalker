<script setup lang="ts">
import MonitoringLogPanel from '../components/MonitoringLogPanel.vue'
import WebSocketStatusBar from '../components/WebSocketStatusBar.vue'
</script>

<template>
  <div class="page-shell monitoring-page">
    <n-flex class="page-section" vertical>
      <n-card class="monitoring-intro-card" content-style="padding: 18px 20px;">
        <n-flex vertical :size="6">
          <n-text depth="3" class="monitoring-kicker">Monitoring</n-text>
          <n-text>
            Track the realtime dashboard streams and reconnect health for this
            Moonwalker installation.
          </n-text>
        </n-flex>
      </n-card>
    </n-flex>
    <n-flex class="page-section" vertical>
      <WebSocketStatusBar />
    </n-flex>
    <n-flex class="page-section" vertical>
      <MonitoringLogPanel />
    </n-flex>
  </div>
</template>

<style scoped>
.monitoring-page {
  gap: 10px;
}

.monitoring-kicker {
  font-size: 0.82rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

</style>
