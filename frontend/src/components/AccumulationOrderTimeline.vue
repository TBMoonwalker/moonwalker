<script setup lang="ts">
import { computed } from 'vue'
import { NTimeline, NTimelineItem } from 'naive-ui'
import type { AccumulationDetail } from '../types/accumulation'
import type { TradeExecutionRow } from '../stores/trades'
import { accumulationOrders } from '../helpers/accumulationOrders'
import { formatTradingViewDate } from '../helpers/date'
import { accumulationActionLabels, accumulationReason } from '../helpers/accumulation'
const props = defineProps<{
  detail: AccumulationDetail | null
  executions?: TradeExecutionRow[]
  dealId?: string | null
  fallback?: Array<{ key: string; title: string; content: string; timestamp: string | number }>
}>()
const items = computed(() => accumulationOrders(props.detail?.orders ?? [], props.executions ?? [], props.dealId, props.fallback))
const base = computed(() => props.detail?.symbol.split('/')[0] ?? '')
const quote = computed(() => props.detail?.symbol.split('/')[1] ?? '')
function date(value?: string | number) {
  if (!value) return undefined
  const timestamp = typeof value === 'string' && !/^\d+$/.test(value) ? Date.parse(value) : Number(value)
  return Number.isFinite(timestamp) ? formatTradingViewDate(timestamp) : undefined
}
const fees = (value: Record<string, string> | null) => value ? Object.entries(value).map(([currency, amount]) => `${amount} ${currency}`).join(' · ') || '0' : 'Unknown'
</script>
<template>
  <n-timeline class="accumulation-order-timeline">
    <n-timeline-item v-for="item in items" :key="item.key" :title="item.key === 'registration' && detail?.observations_initialized ? 'Holding information' : item.title" :time="date(item.timestamp)" :type="item.base ? 'info' : item.checkpoint?.side === 'sell' ? 'warning' : 'success'">
      <p v-if="item.content">{{ item.content }}</p>
      <dl v-if="item.checkpoint" class="order-values">
        <div><dt>Filled · {{ base }}</dt><dd>{{ item.checkpoint.filled_quantity ?? 'Unknown' }}</dd></div>
        <div><dt>{{ item.checkpoint.side === 'buy' ? 'Order cost' : 'Sale proceeds' }} · {{ quote }}</dt><dd>{{ item.checkpoint.quote_cost ?? 'Unknown' }}</dd></div>
        <div v-if="item.price !== undefined"><dt>Reported fill price · {{ quote }}</dt><dd>{{ item.price }}</dd></div>
        <div><dt>Order fees</dt><dd>{{ fees(item.checkpoint.fees) }}</dd></div>
      </dl>
      <p v-if="item.checkpoint && !item.checkpoint.fees_complete">Fee report incomplete; net return is unverified.</p>
      <details v-if="item.checkpoint" class="order-evidence">
        <summary>Inventory after this order</summary>
        <dl v-if="item.checkpoint.inventory_at_update" class="order-values">
          <div><dt>Managed quantity · {{ base }}</dt><dd>{{ item.checkpoint.inventory_at_update.net_quantity ?? 'Unknown' }}</dd></div>
          <div><dt>Remaining cost · {{ quote }}</dt><dd>{{ item.checkpoint.inventory_at_update.remaining_cost ?? 'Unknown' }}</dd></div>
          <div><dt>Contributed · {{ quote }}</dt><dd>{{ item.checkpoint.inventory_at_update.contributed_quote ?? 'Unknown' }}</dd></div>
          <div><dt>Disposal proceeds · {{ quote }}</dt><dd>{{ item.checkpoint.inventory_at_update.disposal_proceeds ?? 'Unknown' }}</dd></div>
          <div><dt>Recorded fees</dt><dd>{{ fees(item.checkpoint.inventory_at_update.fees) }}</dd></div>
          <div><dt>Cost basis</dt><dd>{{ accumulationReason(item.checkpoint.inventory_at_update.basis_provenance) }}</dd></div>
        </dl>
        <p v-else>Inventory evidence unavailable.</p>
        <p>Evidence updated: {{ date(item.checkpoint.updated_at) }} · {{ item.checkpoint.terminal ? 'Settled' : 'Awaiting settlement' }}</p>
      </details>
      <slot v-if="item.base" name="base-order" />
    </n-timeline-item>
    <n-timeline-item v-for="operation in detail?.operations ?? []" :key="operation.operation_id" :title="accumulationActionLabels[operation.action as keyof typeof accumulationActionLabels] ?? accumulationReason(operation.action)" :time="date(operation.created_at)" type="info">
      <p>{{ operation.status }} · {{ accumulationReason(operation.result_state) }}<template v-if="operation.reason"> · {{ accumulationReason(operation.reason) }}</template></p>
      <template v-if="operation.adjustment">
        <p>{{ operation.adjustment.direction }} {{ operation.adjustment.quantity }} {{ base }} · {{ operation.adjustment.note }}</p>
        <p>Quantity: {{ operation.adjustment.before_quantity }} → {{ operation.adjustment.after_quantity }}</p>
        <p>Cost: {{ operation.adjustment.before_cost ?? 'Unknown' }} → {{ operation.adjustment.after_cost ?? 'Unknown' }} {{ quote }}</p>
      </template>
    </n-timeline-item>
  </n-timeline>
  <p v-if="detail?.older_orders_available">Older executed orders remain recorded outside this recent timeline.</p>
  <p v-if="detail?.older_operations_available">Older requests remain recorded outside this recent timeline.</p>
</template>
<style scoped>
.order-values { display: grid; gap: 8px; margin: 8px 0; }
dt, p { font-size: 14px; color: var(--mw-color-text-secondary); }
dd { margin: 0; font-family: var(--mw-font-mono); overflow-wrap: anywhere; }
p { margin: 8px 0; }
summary { cursor: pointer; min-height: 44px; display: flex; align-items: center; font-size: 14px; }
summary:focus-visible { outline: var(--mw-focus-ring); outline-offset: var(--mw-focus-offset); }
</style>
