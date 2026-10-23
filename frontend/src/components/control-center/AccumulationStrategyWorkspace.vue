<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { accumulationErrorStatus, fetchAccumulationStrategies, saveAccumulationStrategy } from '../../api/accumulation'
import { extractApiErrorMessage } from '../../helpers/apiErrors'
import { createOrderOperationId } from '../../helpers/orderMutations'
import type { AccumulationParameters, AccumulationStrategy } from '../../types/accumulation'

const visible = ref(false)
const loading = ref(false)
const saving = ref(false)
const name = ref('Accumulation dip')
const parameters = ref<AccumulationParameters | null>(null)
const strategies = ref<AccumulationStrategy[]>([])
const selected = ref<number | null>(null)
const cursor = ref<number | null>(null)
const timeframes = ref<string[]>([])
const error = ref('')
const notice = ref('')
const request = ref<{ operation_id: string; name: string; parameters: AccumulationParameters } | null>(null)
const decimalFields: { key: keyof Pick<AccumulationParameters, 'entry_atr' | 'spacing_atr' | 'recovery_atr' | 'min_fraction' | 'slope' | 'max_fraction'>; label: string }[] = [
  { key: 'entry_atr', label: 'Minimum correction depth (ATR)' },
  { key: 'spacing_atr', label: 'Further decline before another buy (ATR)' },
  { key: 'recovery_atr', label: 'Recovery before a new correction (ATR)' },
  { key: 'min_fraction', label: 'Starting budget fraction (0–1)' },
  { key: 'slope', label: 'Extra budget fraction per ATR of correction' },
  { key: 'max_fraction', label: 'Maximum budget fraction per buy (0–1)' },
]

async function load(more = false) {
  if (loading.value) return
  loading.value = true
  try {
    const page = await fetchAccumulationStrategies(more ? cursor.value ?? 0 : 0)
    visible.value = true
    strategies.value = more ? [...strategies.value, ...page.versions.filter(row => !strategies.value.some(old => old.id === row.id))] : page.versions
    cursor.value = page.next_after_id
    timeframes.value = page.timeframes
    if (!parameters.value) parameters.value = { ...page.defaults }
    error.value = ''
  } catch (cause) {
    if (accumulationErrorStatus(cause) === 503 && !visible.value) return
    visible.value = true
    error.value = extractApiErrorMessage(cause, 'Could not load accumulation strategies.')
  } finally { loading.value = false }
}

function copyVersion(id: number) {
  const version = strategies.value.find(row => row.id === id)
  if (!version || saving.value || request.value) return
  selected.value = id
  parameters.value = { ...version.parameters }
  name.value = `${version.name} copy`.slice(0, 120)
  notice.value = 'Parameters copied. Saving creates a new immutable strategy variant.'
}

async function save() {
  if (!parameters.value || saving.value) return
  if (!request.value) request.value = {
    operation_id: createOrderOperationId('acc-strategy'), name: name.value,
    parameters: { ...parameters.value },
  }
  saving.value = true
  error.value = ''
  try {
    const result = await saveAccumulationStrategy(request.value)
    request.value = null
    notice.value = `Saved ${result.name} · v${result.version}. Existing holdings keep their current strategy. Apply it in Configuration → Trade modes.`
    await load()
  } catch (cause) {
    if ([400, 409].includes(accumulationErrorStatus(cause) ?? 0)) request.value = null
    error.value = extractApiErrorMessage(cause, 'Save outcome is unknown. Retry the same save to retrieve its result.')
  } finally { saving.value = false }
}

onMounted(() => { void load() })
</script>

<template>
  <section v-if="visible" class="accumulation-strategy-workspace" aria-labelledby="accumulation-strategy-title">
    <h2 id="accumulation-strategy-title">Accumulation strategies</h2>
    <p>Experimental buy-only strategies. Deeper market corrections increase spending within the configured budget fraction. Sales require your action.</p>
    <n-alert v-if="error" type="warning" role="alert">{{ error }}</n-alert>
    <n-alert v-if="notice" type="info" role="status">{{ notice }}</n-alert>
    <label for="accumulation-copy">Copy saved parameters</label>
    <n-select filterable :value="selected" :options="strategies.map(row => ({ label: `${row.name} · v${row.version}`, value: row.id }))" :input-props="{ id: 'accumulation-copy' }" :disabled="saving || !!request" placeholder="Start with defaults or copy a saved strategy" @update:value="copyVersion" />
    <div class="strategy-toolbar">
      <n-button :loading="loading" :disabled="saving" @click="load()">Refresh saved strategies</n-button>
      <n-button v-if="cursor !== null" :disabled="loading || saving" @click="load(true)">Load more saved strategies</n-button>
    </div>
    <n-form v-if="parameters" label-placement="top" :disabled="saving || !!request">
      <n-form-item label="New strategy name" :label-props="{ for: 'accumulation-variant-name' }"><n-input v-model:value="name" :input-props="{ id: 'accumulation-variant-name' }" :maxlength="120" /></n-form-item>
      <div class="strategy-parameter-grid">
        <n-form-item label="Candle timeframe" :label-props="{ for: 'accumulation-variant-timeframe' }"><n-select filterable v-model:value="parameters.timeframe" :input-props="{ id: 'accumulation-variant-timeframe' }" :options="timeframes.map(value => ({ label: value, value }))" /></n-form-item>
        <n-form-item label="Peak lookback (candles)" :label-props="{ for: 'accumulation-variant-peak' }"><n-input-number v-model:value="parameters.peak_length" :input-props="{ id: 'accumulation-variant-peak' }" :min="2" :max="1000" :precision="0" /></n-form-item>
        <n-form-item label="ATR period (candles)" :label-props="{ for: 'accumulation-variant-atr' }"><n-input-number v-model:value="parameters.atr_length" :input-props="{ id: 'accumulation-variant-atr' }" :min="2" :max="100" :precision="0" /></n-form-item>
        <n-form-item v-for="field in decimalFields" :key="field.key" :label="field.label" :label-props="{ for: `accumulation-variant-${field.key}` }"><n-input v-model:value="parameters[field.key]" :input-props="{ id: `accumulation-variant-${field.key}`, inputmode: 'decimal' }" /></n-form-item>
      </div>
    </n-form>
    <p>Every save creates a separate, immutable version 1. There is no automatic update of existing holdings. The budget fractions must satisfy 0 &lt; starting ≤ maximum ≤ 1.</p>
    <n-button type="primary" :loading="saving" :disabled="!parameters || saving" @click="save">{{ request ? 'Retry same strategy save' : 'Save as new accumulation strategy' }}</n-button>
  </section>
</template>

<style scoped>
.accumulation-strategy-workspace { display: grid; gap: 16px; margin-top: 24px; padding: 24px; border: 1px solid var(--mw-color-border); border-radius: var(--mw-radius-sm, 6px); background: var(--mw-color-surface-panel); }
h2, p { margin: 0; }
h2 { font-size: 20px; font-weight: 600; }
p, label { color: var(--mw-color-text-secondary); }
.strategy-parameter-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(260px, 100%), 1fr)); gap: 0 16px; }
.strategy-toolbar { display: flex; flex-wrap: wrap; gap: 12px; }
@media (max-width: 767px) { .accumulation-strategy-workspace { padding: 16px; } .accumulation-strategy-workspace :deep(.n-button), .accumulation-strategy-workspace :deep(.n-input), .accumulation-strategy-workspace :deep(.n-base-selection) { min-height: 44px; } }
</style>
