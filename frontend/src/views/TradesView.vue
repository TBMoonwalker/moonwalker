<script setup lang="ts">
import OpenTrades from '../components/OpenTrades.vue'
import ClosedTrades from '../components/ClosedTrades.vue'
import Statistics from '@/components/Statistics.vue'
import Charts from '@/components/Charts.vue'
import { ConstructOutline } from '@vicons/ionicons5'

import { useRouter } from 'vue-router' // Import useRouter

const router = useRouter() // Initialize Vue Router

function configureButtonClicked() {
  console.log("Configure button clicked!")
  router.push('/config') // Navigate to the Configure component
  // You can add more logic here to handle what happens when the button is clicked
}
</script>

<template>

  <n-flex justify="space-between" :style="{ width: '92%' }" align="center">
    <n-button strong secondary circle type="primary" size="large" @click="configureButtonClicked">
      <template #icon>
        <n-icon>
          <ConstructOutline />
        </n-icon>
      </template>
    </n-button>
    <Statistics />
  </n-flex>
  <n-flex vertical :style="{ display: 'flex', flexDirection: 'column', gap: '16px', width: '98%' }">
    <n-card content-style="padding: 0;">
      <n-tabs type="line" size="large" :tabs-padding="20">
        <n-tab-pane name="Daily profit">
          <Charts period="daily" />
        </n-tab-pane>
        <n-tab-pane name="Monthly profit">
          <Charts period="monthly" />
        </n-tab-pane>
        <n-tab-pane name="Yearly profit">
          <Charts period="yearly" />
        </n-tab-pane>
      </n-tabs>
    </n-card>
  </n-flex>
  <n-flex vertical :style="{ display: 'flex', flexDirection: 'column', gap: '16px', width: '98%' }">
    <n-card content-style="padding: 0;">
      <n-tabs size="large" :tabs-padding="20">
        <n-tab-pane name=" Open Trades">
          <OpenTrades />
        </n-tab-pane>
        <n-tab-pane name="Closed Trades">
          <ClosedTrades />
        </n-tab-pane>
      </n-tabs>
    </n-card>
  </n-flex>
</template>