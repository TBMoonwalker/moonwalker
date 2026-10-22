<script setup lang="ts">
import { computed, ref } from 'vue'
import axios from 'axios'
import { buildMoonwalkerApiUrl } from '../helpers/configEditorDefaults'
import { extractApiErrorMessage } from '../helpers/apiErrors'
import { MOONWALKER_CLIENT_HEADER, MOONWALKER_CLIENT_HEADER_VALUE } from '../api/client'
import type { AccumulationStrategy } from '../types/accumulation'

const props = defineProps<{ strategies: AccumulationStrategy[] }>()
const versionId = ref<number | null>(null)
const funding = ref('1000')
const feeBps = ref('10')
const slippageBps = ref('20')
const interval = ref('24')
const candles = ref('')
const busy = ref(false)
const error = ref('')
interface ReplayResult {
  strategy: string; contributed_quote: string; units: string; spent_quote_including_fees: string
  fees_quote: string; cash_quote: string; ending_value_quote: string; maximum_drawdown_fraction: string; buy_count: number
}
const result = ref<{ results: ReplayResult[]; gap_count: number; warmup_candles: number; evaluation_candles: number; caveats: string[] } | null>(null)
const options = computed(() => props.strategies.map(version => ({ value: version.id, label: `${version.name} · v${version.version} · ${version.parameters.timeframe}` })))
async function run() {
  if (busy.value) return
  error.value = ''
  result.value = null
  if (!versionId.value || !/^\d+$/.test(interval.value) || candles.value.length > 4_000_000) {
    error.value = 'Select a strategy, enter an interval in whole candles, and provide at most 4 MB of candle data.'
    return
  }
  busy.value = true
  try {
    const rows = candles.value.trim().split(/\r?\n/)
    if (rows.length > 20000) throw new Error('At most 20000 candles can be compared.')
    const data = rows.map((line, index) => {
      const parts = line.trim().split(';')
      if (parts.length !== 5 || !/^\d+$/.test(parts[0] ?? '') || !Number.isSafeInteger(Number(parts[0]))) throw new Error(`Candle row ${index + 1} needs close_ms;open;high;low;close.`)
      return { close_ms: Number(parts[0]), open: parts[1], high: parts[2], low: parts[3], close: parts[4] }
    })
    result.value = (await axios.post(buildMoonwalkerApiUrl('/accumulation/replay'), {
      strategy_version_id: versionId.value, funding: funding.value, fee_bps: feeBps.value,
      slippage_bps: slippageBps.value, fixed_interval_candles: Number(interval.value), candles: data,
    }, { headers: { [MOONWALKER_CLIENT_HEADER]: MOONWALKER_CLIENT_HEADER_VALUE } })).data
  } catch (cause) {
    error.value = extractApiErrorMessage(cause, cause instanceof Error ? cause.message : 'Historical comparison failed.')
  } finally { busy.value = false }
}
</script>

<template>
  <details class="accumulation-replay">
    <summary>Historical strategy comparison</summary>
    <p>Simulation only. Compare equal initial funding after warmup with buy-and-hold and fixed-interval DCA. This does not use your wallet or submit orders.</p>
    <form @submit.prevent="run">
      <label for="replay-strategy">Saved accumulation strategy</label>
      <n-select filterable :input-props="{ id: 'replay-strategy' }" v-model:value="versionId" :options="options" :disabled="busy" />
      <label for="replay-funding">Initial funding · symbol quote currency</label>
      <n-input :input-props="{ id: 'replay-funding' }" v-model:value="funding" :disabled="busy" />
      <label for="replay-fee">Buy fee · basis points (10 = 0.1%)</label>
      <n-input :input-props="{ id: 'replay-fee' }" v-model:value="feeBps" :disabled="busy" />
      <label for="replay-slippage">Adverse buy slippage · basis points</label>
      <n-input :input-props="{ id: 'replay-slippage' }" v-model:value="slippageBps" :disabled="busy" />
      <label for="replay-interval">Fixed DCA interval · candles</label>
      <n-input :input-props="{ id: 'replay-interval' }" v-model:value="interval" :disabled="busy" />
      <label for="replay-candles">Completed OHLC candles · close_ms;open;high;low;close</label>
      <n-input :input-props="{ id: 'replay-candles' }" v-model:value="candles" type="textarea" :autosize="{ minRows: 4, maxRows: 12 }" :disabled="busy" placeholder="UTC closing timestamp in milliseconds;open;high;low;close" />
      <p>Supply the selected strategy's warmup plus at least two evaluation candles, in ascending order, without a header. Maximum 20000 candles. Missing intervals are reported and block new signals until warmup is contiguous.</p>
      <n-button attr-type="submit" :loading="busy" :disabled="busy">Run historical comparison</n-button>
    </form>
    <p v-if="error" role="alert">{{ error }}</p>
    <div v-if="result" aria-live="polite">
      <p>{{ result.warmup_candles }} warmup candles · {{ result.evaluation_candles }} evaluation candles · {{ result.gap_count }} gaps.</p>
      <div class="replay-table">
        <table>
          <caption>Historical comparison · quote amounts include modeled buy fees</caption>
          <thead><tr><th>Strategy</th><th>Units</th><th>Spent</th><th>Fees</th><th>Cash</th><th>Ending value</th><th>Maximum drawdown fraction</th><th>Buys</th></tr></thead>
          <tbody><tr v-for="row in result.results" :key="row.strategy"><th>{{ row.strategy.replaceAll('_', ' ') }}</th><td>{{ row.units }}</td><td>{{ row.spent_quote_including_fees }}</td><td>{{ row.fees_quote }}</td><td>{{ row.cash_quote }}</td><td>{{ row.ending_value_quote }}</td><td>{{ row.maximum_drawdown_fraction }}</td><td>{{ row.buy_count }}</td></tr></tbody>
        </table>
      </div>
      <p v-for="caveat in result.caveats" :key="caveat">{{ caveat }}</p>
    </div>
  </details>
</template>

<style scoped>
.accumulation-replay { margin-block: 1rem; min-width: 0; max-width: 100%; overflow-wrap: anywhere; }
summary, label { display: block; margin-block: 0.75rem; }
summary { cursor: pointer; min-height: 44px; }
.replay-table { max-width: 100%; overflow-x: auto; }
th, td { padding: 0.5rem; text-align: left; vertical-align: top; font-variant-numeric: tabular-nums; }
td { max-width: 14rem; overflow-wrap: anywhere; }
</style>
