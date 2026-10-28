<script setup lang="ts">
import { computed, onActivated, onDeactivated, onMounted, onUnmounted, ref } from 'vue'
import { fetchJson } from '../api/client'
import { MOONWALKER_API_ORIGIN } from '../config'

interface Holding {
  symbol: string
  quantity: string | null
  remaining_cost: string | null
  average_cost: string | null
  market_value: string | null
  unrealized: string | null
  complete: boolean
  basis_provenance: string | null
}
interface Performance {
  observed_at_ms: number
  valid_until_ms: number
  includes_csv_declarations: boolean
  pending_entry_count?: number | null
  holdings: Holding[]
  by_quote: Array<{ quote: string; contributed_quote: string | null; remaining_cost: string | null; market_value: string | null; realized: string | null; unrealized: string | null; total_return: string | null; complete: boolean; unknown_deal_count: number; live_holding_count: number }>
}
interface ActivityItem {
  kind: 'order' | 'csv'
  id: number
  updated_at: string
  symbol: string
  quantity?: string | null
  quote_cost?: string | null
  price_per_coin?: string | null
  side?: string
  fees_complete?: boolean
  terminal?: boolean
  declaration_complete?: boolean
}
interface ActivityPage { items: ActivityItem[]; next_cursor: string | null }
const data = ref<Performance | null>(null)
const connected = ref(false)
const activity = ref<ActivityItem[]>([])
const activityCursor = ref<string | null>(null)
const activityError = ref('')
const activityNotice = ref('')
const activityLoading = ref(false)
const activityLoaded = ref(false)
const now = ref(Date.now())
let timer: ReturnType<typeof setInterval> | undefined
let reconnectTimer: ReturnType<typeof setTimeout> | undefined
let activityRetryTimer: ReturnType<typeof setTimeout> | undefined
let socket: WebSocket | undefined
let active = false
let activityRevision: number | null = null
let activityReloadPending = false
let accountGeneration: number | null = null
let activityEpoch = 0
let waitingForReconnect = false
const fresh = computed(() => !!data.value && now.value < data.value.valid_until_ms)
function display(value: string | null | undefined) {
  if (value == null) return 'Unavailable'
  const match = /^(-?)(\d+)(?:\.(\d+))?$/.exec(value)
  if (!match) return 'Unavailable'
  return `${match[1]}${match[2]}.${((match[3] ?? '') + '00').slice(0, 2)}`
}
function displayQuantity(value: string | null | undefined) {
  if (value == null) return 'Unavailable'
  const match = /^(-?)(\d+)(?:\.(\d+))?$/.exec(value)
  if (!match) return 'Unavailable'
  return `${match[1]}${match[2]}.${(match[3] ?? '').padEnd(4, '0')}`
}
function connect() {
  if (!active || socket) return
  const url = new URL('/accumulation/performance/stream', MOONWALKER_API_ORIGIN)
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  const current = new WebSocket(url.toString())
  socket = current
  current.onmessage = event => {
    if (socket !== current || !active) return
    try {
      const message = JSON.parse(String(event.data))
      if (message.type !== 'snapshot' || !message.performance || !Array.isArray(message.performance.holdings) || !Array.isArray(message.performance.by_quote)) {
        connected.value = false
        return
      }
      const wasConnected = connected.value
      connected.value = true
      waitingForReconnect = false
      data.value = message.performance as Performance
      now.value = Date.now()
      if (Number.isSafeInteger(message.account_generation)) {
        if (accountGeneration === null || accountGeneration !== message.account_generation) {
          activityEpoch++
          activity.value = []
          activityCursor.value = null
          activityLoaded.value = false
          activityNotice.value = ''
          activityReloadPending = true
        }
        accountGeneration = message.account_generation
      }
      if (Number.isSafeInteger(message.activity_revision)) {
        if (activityRevision === null || activityRevision !== message.activity_revision) {
          if (activityRevision !== null && activityLoaded.value) activityNotice.value = 'Activity changed; showing the latest records.'
          activityReloadPending = true
        }
        activityRevision = message.activity_revision
      }
      if ((!wasConnected && activityError.value) || activityReloadPending) void loadActivity(true)
    } catch { connected.value = false }
  }
  current.onclose = () => {
    if (socket !== current) return
    socket = undefined
    connected.value = false
    waitingForReconnect = true
    accountGeneration = null
    activityEpoch++
    activity.value = []
    activityCursor.value = null
    activityLoaded.value = false
    activityReloadPending = true
    if (active) reconnectTimer = setTimeout(connect, 2000)
  }
  current.onerror = () => { current.close() }
}
async function loadActivity(restart = false) {
  if (activityLoading.value) { if (restart) activityReloadPending = true; return }
  if (activityRetryTimer) clearTimeout(activityRetryTimer)
  activityRetryTimer = undefined
  activityLoading.value = true
  const epoch = activityEpoch
  if (restart) activityReloadPending = false
  activityError.value = ''
  try {
    const cursor = restart ? null : activityCursor.value
    const result = await fetchJson<ActivityPage>(`/accumulation/activity${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ''}`)
    if (epoch !== activityEpoch) return
    activity.value = restart ? result.items : [...activity.value, ...result.items]
    activityCursor.value = result.next_cursor
    activityLoaded.value = true
  } catch (error) {
    if (epoch !== activityEpoch) return
    if (!restart && error instanceof Error && error.message.includes('409')) {
      activityNotice.value = 'Activity changed; showing the latest records.'
      activityReloadPending = true
    }
    else {
      activityError.value = 'Activity history could not be loaded; retrying.'
      if (active) activityRetryTimer = setTimeout(() => { void loadActivity(true) }, 5000)
    }
  } finally {
    activityLoading.value = false
    if (active && !waitingForReconnect && activityReloadPending) void loadActivity(true)
  }
}
function start() {
  if (active) return
  active = true
  connect()
  void loadActivity(true)
  timer = setInterval(() => { now.value = Date.now() }, 1000)
}
function stop() {
  active = false
  connected.value = false
  waitingForReconnect = false
  activityEpoch++
  accountGeneration = null
  activityRevision = null
  activity.value = []
  activityCursor.value = null
  activityLoaded.value = false
  activityNotice.value = ''
  if (timer) clearInterval(timer)
  if (reconnectTimer) clearTimeout(reconnectTimer)
  if (activityRetryTimer) clearTimeout(activityRetryTimer)
  const current = socket
  socket = undefined
  current?.close()
}
onMounted(start)
onActivated(start)
onDeactivated(stop)
onUnmounted(stop)
</script>

<template>
  <section aria-label="Accumulation statistics" class="accumulation-statistics">
    <h2>Accumulation</h2>
    <p v-if="!data" role="status">Connecting to accumulation statistics…</p>
    <template v-else>
      <p role="status">{{ !fresh ? 'Valuation is stale; market values are unavailable.' : !connected ? 'Reconnecting; last bid values are shown until they expire.' : `Bid values observed ${new Date(data.observed_at_ms).toLocaleString()}; before future sale fees.` }}</p>
      <p v-if="data.includes_csv_declarations">Returns include CSV-declared costs and fees where available.</p>
      <div v-for="group in data.by_quote" :key="group.quote" class="summary">
        <h3>{{ group.quote }} totals</h3>
        <p>Contributed funds: {{ display(group.contributed_quote) }} · Remaining basis: {{ display(group.remaining_cost) }} · Market value: {{ fresh ? display(group.market_value) : 'Unavailable' }} · Realized: {{ display(group.realized) }} · Unrealized: {{ fresh ? display(group.unrealized) : 'Unavailable' }} · Total return: {{ fresh ? display(group.total_return) : 'Unavailable' }}</p>
        <p>{{ group.live_holding_count }} managed holdings · {{ group.unknown_deal_count }} records with incomplete return evidence.</p>
        <p v-if="group.contributed_quote == null">Contributed funds are unavailable because purchase or fee evidence is incomplete.</p>
        <p v-if="group.remaining_cost == null">Remaining basis is unavailable because managed ownership or cost evidence is incomplete.</p>
        <p v-if="!fresh || group.market_value == null">Market value is unavailable because a current verified bid or ownership is missing.</p>
        <p v-if="!group.complete">Returns are unavailable because evidence or current valuations are incomplete.</p>
      </div>
      <p v-if="!data.holdings?.length">No managed accumulation holdings.</p>
      <p v-if="data.pending_entry_count" role="status">{{ data.pending_entry_count }} accumulation {{ data.pending_entry_count === 1 ? 'entry is' : 'entries are' }} awaiting completion.</p>
      <div v-if="data.holdings.length" class="holdings-table table-wrap">
        <table>
          <caption>Managed holdings</caption>
          <thead><tr><th>Asset</th><th>Quantity</th><th>Remaining cost</th><th>Average cost per coin</th><th>Bid value</th><th>Unrealized return</th></tr></thead>
          <tbody><tr v-for="holding in data.holdings" :key="holding.symbol">
            <th scope="row">{{ holding.symbol }}<small v-if="holding.basis_provenance?.startsWith('csv')">CSV-declared basis</small><small v-if="!holding.complete">Return evidence incomplete</small></th>
            <td>{{ displayQuantity(holding.quantity) }}</td><td>{{ display(holding.remaining_cost) }}</td><td>{{ display(holding.average_cost) }}</td>
            <td>{{ fresh ? display(holding.market_value) : 'Unavailable' }}</td><td>{{ fresh ? display(holding.unrealized) : 'Unavailable' }}</td>
          </tr></tbody>
        </table>
      </div>
      <div v-if="data.holdings.length" class="mobile-holdings" aria-label="Managed holdings">
        <details v-for="holding in data.holdings" :key="holding.symbol">
          <summary><strong>{{ holding.symbol }}</strong><span>{{ displayQuantity(holding.quantity) }} <span aria-hidden="true">▾</span></span></summary>
          <p>Remaining cost: {{ display(holding.remaining_cost) }}</p>
          <p>Average cost per coin: {{ display(holding.average_cost) }}</p>
          <p>Bid value: {{ fresh ? display(holding.market_value) : 'Unavailable' }}</p>
          <p>Unrealized return: {{ fresh ? display(holding.unrealized) : 'Unavailable' }}</p>
          <p v-if="holding.basis_provenance?.startsWith('csv')">CSV-declared basis</p>
          <p v-if="!holding.complete">Return evidence incomplete</p>
        </details>
      </div>
      <p>Quantities show at least four decimal places. Other amounts are truncated to two decimal places and use the quote currency shown in each symbol.</p>
    </template>
    <section aria-label="Accumulation activity">
      <h3>Accumulation activity</h3>
      <p>Order rows are cumulative summaries, not individual fills. Price per coin is the recorded quote amount divided by the filled quantity, before fees. CSV prices use declared basis per net coin. Times are shown in your local timezone.</p>
      <p v-if="activityNotice" role="status">{{ activityNotice }}</p>
      <p v-if="activityError" role="alert">{{ activityError }} Previously loaded records may be out of date.</p>
      <p v-if="activityLoading && !activityLoaded">Loading activity…</p>
      <p v-else-if="activityLoaded && !activity.length">No accumulation activity recorded for this account.</p>
      <p v-if="activity.length" class="mobile-table-hint">Scroll the table to see price and fee details.</p>
      <div v-if="activity.length" class="table-wrap">
        <table>
          <caption>Recorded orders and declarations</caption>
          <thead><tr><th>Updated</th><th>Symbol</th><th>Record</th><th>Quantity</th><th>Quote amount</th><th>Price per coin</th><th>Evidence</th></tr></thead>
          <tbody><tr v-for="item in activity" :key="`${item.kind}-${item.id}`">
            <td>{{ new Date(item.updated_at).toLocaleString() }}</td><th scope="row">{{ item.symbol }}</th>
            <td>{{ item.kind === 'csv' ? 'CSV declaration' : `${item.side} order summary` }}</td>
            <td>{{ displayQuantity(item.quantity) }}</td><td>{{ display(item.quote_cost) }}</td><td>{{ display(item.price_per_coin) }}</td>
            <td>{{ item.declaration_complete === false ? 'Declaration unavailable' : item.fees_complete ? 'Fees recorded' : 'Fees incomplete' }}<span v-if="item.kind === 'order' && !item.terminal"> · Order open</span></td>
          </tr></tbody>
        </table>
      </div>
      <button v-if="activityCursor && !activityError" type="button" :disabled="activityLoading" @click="loadActivity()">{{ activityLoading ? 'Loading…' : 'Load older activity' }}</button>
    </section>
  </section>
</template>

<style scoped>
.accumulation-statistics { border: 1px solid var(--mw-color-border); border-radius: 10px; padding: 16px; background: var(--mw-color-surface-panel); }
h2, h3 { margin: 0 0 8px; }
p { margin: 8px 0; color: var(--mw-color-text-secondary); }
.summary { margin: 16px 0; }
.table-wrap { max-width: 100%; overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }
caption { text-align: left; font-weight: 600; padding: 8px 0; }
th, td { text-align: left; padding: 8px 12px; border-bottom: 1px solid var(--mw-color-border); }
small { display: block; color: var(--mw-color-text-secondary); }
button { min-height: 44px; margin: 4px 8px 4px 0; }
.mobile-table-hint { display: none; }
.mobile-holdings { display: none; }
@media (max-width: 767px) {
  .mobile-table-hint, .mobile-holdings { display: block; }
  .holdings-table { display: none; }
  .mobile-holdings details { border-bottom: 1px solid var(--mw-color-border); padding: 0 8px; }
  .mobile-holdings summary { min-height: 44px; display: flex; align-items: center; justify-content: space-between; gap: 16px; cursor: pointer; }
  .mobile-holdings summary:focus-visible { outline: 2px solid var(--mw-color-primary); outline-offset: 2px; }
}
</style>
