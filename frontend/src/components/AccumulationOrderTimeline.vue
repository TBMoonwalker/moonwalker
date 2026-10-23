<script setup lang="ts">
import { computed } from 'vue'
import { NTimeline, NTimelineItem } from 'naive-ui'
import type { AccumulationDetail } from '../types/accumulation'
import type { TradeExecutionRow } from '../stores/trades'
import { accumulationOrders } from '../helpers/accumulationOrders'
import { formatTradingViewDate } from '../helpers/date'
const props = defineProps<{
  detail: AccumulationDetail | null
  executions?: TradeExecutionRow[]
  dealId?: string | null
  fallback?: Array<{ key: string; title: string; content: string; timestamp: string | number }>
}>()
const items = computed(() => accumulationOrders(props.detail?.orders ?? [], props.executions ?? [], props.dealId ?? props.detail?.holding?.deal_id, props.fallback))
function date(value?: string | number) {
  if (!value) return undefined
  const timestamp = typeof value === 'string' && !/^\d+$/.test(value) ? Date.parse(value) : Number(value)
  return Number.isFinite(timestamp) ? formatTradingViewDate(timestamp) : undefined
}
function content(item: ReturnType<typeof accumulationOrders>[number]) {
  if (!item.checkpoint) return item.content
  return `Order size: ${item.checkpoint.quote_cost ?? 'Unknown'} | Amount: ${item.checkpoint.filled_quantity ?? 'Unknown'} | Price: ${item.price ?? 'Unknown'}`
}
</script>
<template>
  <n-timeline v-if="items.some(item => item.key !== 'registration')" class="accumulation-order-timeline" :horizontal="false">
    <n-timeline-item
      v-for="item in items.filter(item => item.key !== 'registration')"
      :key="item.key"
      :title="item.title"
      :content="content(item)"
      :time="date(item.timestamp)"
      :type="item.base ? 'info' : item.checkpoint?.side === 'sell' ? 'warning' : 'success'"
    />
  </n-timeline>
  <slot name="base-order" />
</template>
