<script setup lang="ts">
import MonitoringLogPanel from '../components/MonitoringLogPanel.vue'
import WebSocketStatusBar from '../components/WebSocketStatusBar.vue'
</script>

<template>
  <div class="page-shell monitoring-page operator-console-page">
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
  gap: 12px;
}

.page-section {
  min-width: 0;
}
</style>
