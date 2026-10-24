<script setup lang="ts">
import { computed, h, onMounted, reactive, ref, watch, type Directive } from 'vue'
import type { DataTableColumns, SelectOption } from 'naive-ui'
import {
    CalendarOutline,
    FlaskOutline,
    PlayCircleOutline,
    RefreshOutline,
} from '@vicons/ionicons5'

import { fetchJson } from '../api/client'
import { useAccumulationStrategies } from '../composables/useAccumulationStrategies'
import BacktestResultChart from '../components/BacktestResultChart.vue'
import { extractApiErrorMessage } from '../helpers/apiErrors'
import {
    BACKTEST_TIMEFRAME_OPTIONS,
    buildBacktestRequest,
    computeBacktestComparison,
    createDefaultBacktestForm,
    createDefaultBacktestRange,
    formatBacktestDelta,
    formatBacktestNumber,
    getBacktestSummary,
    normalizeBacktestSymbolsForCurrency,
    type BacktestFormState,
    type AccumulationBacktestFill,
    type BacktestResult,
    type BacktestTrade,
} from '../helpers/backtest'

interface StrategyListResponse {
    strategies?: Array<{
        slug: string
        name?: string
    }>
}

interface ConfigSnapshotResponse {
    currency?: string | null
    timeframe?: string | null
}

interface ExchangeSymbolsResponse {
    symbols?: string[]
}

const form = reactive<BacktestFormState>(createDefaultBacktestForm())
const dateRange = ref<[number, number] | null>(createDefaultBacktestRange())
const result = ref<BacktestResult | null>(null)
const previousResult = ref<BacktestResult | null>(null)
const isRunning = ref(false)
const isLoadingStrategies = ref(false)
const isLoadingSymbols = ref(false)
const errorMessage = ref('')
const symbolLoadError = ref('')
const configuredCurrency = ref('')
const configuredTimeframe = ref(form.timeframe)
const strategyOptions = ref<SelectOption[]>([])
const symbolOptions = ref<SelectOption[]>([])
const { versions: accumulationStrategies, cursor: accumulationCursor,
    error: accumulationLoadError, load: loadStrategyPage } = useAccumulationStrategies(
        cause => extractApiErrorMessage(cause, 'Saved accumulation strategies could not be loaded.'),
    )
const isAccumulation = computed(() => form.tradeMode === 'accumulation')
const selectedAccumulation = computed(() => accumulationStrategies.value.find(version => version.id === form.accumulationVersionId))
const accumulationOptions = computed(() => accumulationStrategies.value.map(version => ({ value: version.id, label: `${version.name} · v${version.version} · ${version.parameters.timeframe}` })))
watch([isAccumulation, configuredTimeframe], () => {
    if (isAccumulation.value) form.timeframe = configuredTimeframe.value
})
const lastRunAt = ref<number | null>(null)

function labelStepperButtons(element: HTMLElement, fieldLabel: string): void {
    const [decreaseButton, increaseButton] = Array.from(
        element.querySelectorAll<HTMLButtonElement>('button'),
    )
    const normalizedLabel = fieldLabel.toLowerCase()
    decreaseButton?.setAttribute('aria-label', `Decrease ${normalizedLabel}`)
    increaseButton?.setAttribute('aria-label', `Increase ${normalizedLabel}`)
}

const vAccessibleStepper: Directive<HTMLElement, string> = {
    mounted(element, binding) {
        labelStepperButtons(element, binding.value)
    },
    updated(element, binding) {
        labelStepperButtons(element, binding.value)
    },
}

const timeframeOptions = BACKTEST_TIMEFRAME_OPTIONS.map((option) => ({ ...option }))
const symbolPlaceholder = computed(() =>
    configuredCurrency.value
         ? `Select ${configuredCurrency.value} market`
          : 'Load exchange symbols',
)

const canRun = computed(() => {
    if (!dateRange.value) {
        return false
       }
    const hasStrategy = isAccumulation.value ? !!selectedAccumulation.value : form.strategySlug.trim().length > 0
    return (
        form.symbol.trim().length > 0 &&
        hasStrategy &&
        dateRange.value[1] > dateRange.value[0]
      )
})

const summary = computed(() => getBacktestSummary(result.value))
const comparison = computed(() =>
    computeBacktestComparison(result.value, previousResult.value),
)
const comparisonTone = computed(() => {
    if (!comparison.value) {
        return 'neutral'
    }
    if (comparison.value.profitDelta > 0) {
        return 'positive'
    }
    if (comparison.value.profitDelta < 0) {
        return 'negative'
    }
    return 'neutral'
})

const accumulationOutcome = computed(() => result.value?.accumulation?.results.find(row => row.strategy === 'accumulation'))
const statTiles = computed(() => accumulationOutcome.value ? [
    { label: 'Buys', value: String(accumulationOutcome.value.buy_count) },
    { label: 'Coins accumulated', value: formatBacktestNumber(Number(accumulationOutcome.value.units), 8) },
    { label: 'Spent incl. fees', value: formatBacktestNumber(Number(accumulationOutcome.value.spent_quote_including_fees), 2) },
    { label: 'Cash remaining', value: formatBacktestNumber(Number(accumulationOutcome.value.cash_quote), 2) },
    { label: 'Ending value', value: formatBacktestNumber(Number(accumulationOutcome.value.ending_value_quote), 2) },
    { label: 'Max drawdown', value: `${formatBacktestNumber(Number(accumulationOutcome.value.maximum_drawdown_fraction) * 100)}%` },
] : [
    {
        label: 'Trades',
        value: String(summary.value.total_trades ?? 0),
    },
    {
        label: 'Win rate',
        value: `${formatBacktestNumber(summary.value.win_rate, 2)}%`,
    },
    {
        label: 'Total profit',
        value: formatBacktestNumber(summary.value.total_profit, 2),
        tone: Number(summary.value.total_profit ?? 0) >= 0 ? 'positive' : 'negative',
    },
    {
        label: 'Avg profit',
        value: `${formatBacktestNumber(summary.value.avg_profit_percent, 2)}%`,
        tone:
            Number(summary.value.avg_profit_percent ?? 0) >= 0
                ? 'positive'
                : 'negative',
    },
    {
        label: 'Max drawdown',
        value: `${formatBacktestNumber(
            result.value?.stats?.drawdown?.max_drawdown_percent,
            2,
        )}%`,
        tone: 'warning',
    },
    {
        label: 'Candles',
        value: String(result.value?.stats?.candles_evaluated ?? 0),
    },
])

const tradeColumns: DataTableColumns<BacktestTrade> = [
    {
        title: 'Symbol',
        key: 'symbol',
        width: 120,
    },
    {
        title: 'Opened',
        key: 'open_timestamp',
        width: 170,
        render(row) {
            return formatBacktestTimestamp(row.open_timestamp)
        },
    },
    {
        title: 'Entry',
        key: 'open_price',
        width: 120,
        render(row) {
            return formatBacktestNumber(row.open_price, 6)
        },
    },
    {
        title: 'Closed',
        key: 'close_timestamp',
        width: 170,
        render(row) {
            return formatBacktestTimestamp(row.close_timestamp)
        },
    },
    {
        title: 'Exit',
        key: 'close_price',
        width: 120,
        render(row) {
            return formatBacktestNumber(row.close_price, 6)
        },
    },
    {
        title: 'Profit',
        key: 'profit',
        width: 120,
        render(row) {
            const color = row.profit >= 0 ? '#2E7D5B' : '#B4443F'
            return h('span', { style: { color } }, formatBacktestNumber(row.profit))
        },
    },
    {
        title: 'Profit %',
        key: 'profit_percent',
        width: 110,
        render(row) {
            const color = row.profit_percent >= 0 ? '#2E7D5B' : '#B4443F'
            return h(
                'span',
                { style: { color } },
                `${formatBacktestNumber(row.profit_percent)}%`,
            )
        },
    },
    {
        title: 'SO',
        key: 'safety_orders_count',
        width: 72,
    },
    {
        title: 'Exit reason',
        key: 'sell_reason',
        width: 140,
    },
]

const accumulationTradeColumns: DataTableColumns<AccumulationBacktestFill> = [
    { title: 'Bought', key: 'execution_open_ms', render: row => formatBacktestTimestamp(row.execution_open_ms) },
    { title: 'Signal close', key: 'signal_close_ms', render: row => formatBacktestTimestamp(row.signal_close_ms) },
    { title: 'Quantity', key: 'quantity' }, { title: 'Price', key: 'execution_price' },
    { title: 'Spent incl. fees', key: 'spent' }, { title: 'Fee', key: 'fee' },
]
const accumulationComparisonColumns = [
    { title: 'Strategy', key: 'strategy', render: (row: { strategy: string }) => row.strategy.replaceAll('_', ' ') },
    { title: 'Coins', key: 'units' }, { title: 'Spent incl. fees', key: 'spent_quote_including_fees' },
    { title: 'Fees', key: 'fees_quote' }, { title: 'Cash', key: 'cash_quote' }, { title: 'Ending value', key: 'ending_value_quote' },
    { title: 'Max drawdown', key: 'maximum_drawdown_fraction', render: (row: { maximum_drawdown_fraction: string }) => `${formatBacktestNumber(Number(row.maximum_drawdown_fraction) * 100)}%` },
    { title: 'Buys', key: 'buy_count' },
]
async function loadAccumulationStrategies(more = false) {
    const page = await loadStrategyPage(more)
    if (page && !form.accumulationVersionId) form.accumulationVersionId = page.versions[0]?.id ?? null
}
watch(isAccumulation, enabled => { resetResult(); if (enabled && !accumulationStrategies.value.length) void loadAccumulationStrategies() })

const hasResult = computed(() => result.value !== null)
const statusText = computed(() => {
    if (isRunning.value) {
        return 'Running'
    }
    if (errorMessage.value) {
        return 'Needs attention'
    }
    if (result.value?.stats?.still_open_at_end) {
        return 'Open at end'
    }
    if (result.value) {
        return 'Complete'
    }
    return 'Ready'
})
const statusTagType = computed(() => {
    if (errorMessage.value) {
        return 'error'
    }
    if (isRunning.value || result.value?.stats?.still_open_at_end) {
        return 'warning'
    }
    if (result.value) {
        return 'success'
    }
    return 'default'
})

const statusToneClass = computed(
   () =>
    statusTagType.value === 'error' || statusTagType.value === 'warning'
      ? 'is-warning'
      : 'is-open',
)

const lastRunLabel = computed(() =>
    lastRunAt.value ? new Date(lastRunAt.value).toLocaleString() : 'No run yet',
)

function formatBacktestTimestamp(timestamp: number): string {
    return new Date(timestamp).toLocaleString()
}

async function loadStrategies(): Promise<void> {
    isLoadingStrategies.value = true
    try {
        const payload = await fetchJson<StrategyListResponse>('/strategies')
        strategyOptions.value = (payload.strategies ?? []).map((strategy) => ({
            label: strategy.name
                ? `${strategy.name} (${strategy.slug})`
                : strategy.slug,
            value: strategy.slug,
        }))
        if (!form.strategySlug && strategyOptions.value.length > 0) {
            form.strategySlug = String(strategyOptions.value[0].value)
        }
    } catch {
        strategyOptions.value = []
    } finally {
        isLoadingStrategies.value = false
    }
}

function normalizeSymbolOptions(symbols: string[], currency: string): SelectOption[] {
    return normalizeBacktestSymbolsForCurrency(symbols, currency)
        .map((symbol) => ({
            label: symbol,
            value: symbol,
        }))
}

async function loadExchangeSymbols(): Promise<void> {
    isLoadingSymbols.value = true
    symbolLoadError.value = ''

    try {
        const config = await fetchJson<ConfigSnapshotResponse>('/config/all')
        const currency = String(config.currency ?? '').trim().toUpperCase()
        configuredCurrency.value = currency
        configuredTimeframe.value = String(config.timeframe ?? form.timeframe)

        if (!currency) {
            symbolOptions.value = []
            symbolLoadError.value = 'Configure a quote currency before selecting symbols.'
            return
        }

        const payload = await fetchJson<ExchangeSymbolsResponse>(
            `/data/exchange/symbols/${encodeURIComponent(currency)}`,
        )
        symbolOptions.value = normalizeSymbolOptions(payload.symbols ?? [], currency)

        if (symbolOptions.value.length === 0) {
            symbolLoadError.value = `No ${currency} symbols returned by the exchange.`
            form.symbol = ''
            return
        }

        const optionValues = new Set(
            symbolOptions.value.map((option) => String(option.value)),
        )
        if (!optionValues.has(form.symbol)) {
            form.symbol = String(symbolOptions.value[0].value)
        }
    } catch {
        symbolOptions.value = []
        symbolLoadError.value = 'Failed to load symbols from exchange.'
    } finally {
        isLoadingSymbols.value = false
    }
}

async function runBacktest(): Promise<void> {
    if (!canRun.value || !dateRange.value) {
        return
    }

    isRunning.value = true
    errorMessage.value = ''

    try {
        const nextResult = await fetchJson<BacktestResult>('/backtest/run', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(buildBacktestRequest(form, dateRange.value)),
        })
        if (result.value) {
            previousResult.value = result.value
        }
        result.value = nextResult
        lastRunAt.value = Date.now()
    } catch (error) {
        errorMessage.value = extractApiErrorMessage(
            error,
            'Backtest request failed',
        )
    } finally {
        isRunning.value = false
    }
}

function resetResult(): void {
    result.value = null
    previousResult.value = null
    errorMessage.value = ''
    lastRunAt.value = null
}

onMounted(() => {
    void loadStrategies()
    void loadExchangeSymbols()
})
</script>

<template>
    <div class="page-shell backtest-page operator-console-page">
        <header class="operator-page-heading">
            <h1>Backtest</h1>
            <p>Replay a strategy against historical market data and inspect the results.</p>
        </header>
        <section
          class="admission-strip backtest-status-strip"
          :class="statusToneClass"
          aria-live="polite"
        >
            <n-tag
                class="admission-pill"
                :type="statusTagType"
                :bordered="false"
            >
                {{ statusText }}
            </n-tag>
            <span class="admission-copy">
                Strategy replay workspace. Last run: {{ lastRunLabel }}.
            </span>
        </section>

        <section class="backtest-workspace">
            <form class="backtest-controls dashboard-panel" @submit.prevent="runBacktest">
                <div class="panel-title-row">
                    <n-icon size="18"><FlaskOutline /></n-icon>
                    <h2>Run setup</h2>
                </div>

                <n-form
                    class="backtest-form"
                    label-placement="top"
                    :show-feedback="false"
                >
                    <n-form-item label="Trade mode">
                        <n-select filterable v-model:value="form.tradeMode" :disabled="isRunning" :input-props="{ 'aria-label': 'Backtest trade mode' }" :options="[{ label: 'Dynamic DCA', value: 'dynamic_dca' }, { label: 'Accumulation', value: 'accumulation' }]" />
                    </n-form-item>
                    <n-form-item label="Symbol">
                        <n-flex vertical class="symbol-picker">
                            <n-alert
                                v-if="symbolLoadError"
                                type="warning"
                                :show-icon="false"
                            >
                                {{ symbolLoadError }}
                            </n-alert>
                            <n-input-group>
                                <n-select
                                    v-model:value="form.symbol"
                                    filterable
                                    :loading="isLoadingSymbols"
                                    :disabled="symbolOptions.length === 0"
                                    :options="symbolOptions"
                                    :placeholder="symbolPlaceholder"
                                />
                                <n-button
                                    secondary
                                    aria-label="Refresh symbols"
                                    :loading="isLoadingSymbols"
                                    @click="loadExchangeSymbols"
                                >
                                    <template #icon>
                                        <n-icon><RefreshOutline /></n-icon>
                                    </template>
                                </n-button>
                            </n-input-group>
                        </n-flex>
                        <n-input
                            v-if="symbolOptions.length === 0 && !isLoadingSymbols"
                            v-model:value="form.symbol"
                            placeholder="BTC/USDT"
                            autocomplete="off"
                            class="symbol-fallback-input"
                        />
                    </n-form-item>

                     <n-form-item label="Strategy">
                         <template v-if="isAccumulation">
                             <n-select filterable v-model:value="form.accumulationVersionId" :input-props="{ 'aria-label': 'Backtest accumulation strategy' }" :options="accumulationOptions" placeholder="Select a saved version" />
                             <p v-if="accumulationLoadError" role="alert">{{ accumulationLoadError }}</p>
                             <n-button v-if="accumulationCursor !== null || accumulationLoadError" @click="loadAccumulationStrategies(accumulationCursor !== null)">Load strategies</n-button>
                         </template>
                         <n-select
                             v-else-if="strategyOptions.length > 0"
                             v-model:value="form.strategySlug"
                             filterable
                              :loading="isLoadingStrategies"
                              :options="strategyOptions"
                         />
                         <n-input
                             v-else
                             v-model:value="form.strategySlug"
                             placeholder="ema20_swing"
                             autocomplete="off"
                         />
                     </n-form-item>

                     <div class="control-grid two numeric-grid">
                        <n-form-item :label="isAccumulation ? 'Timeframe · from Exchange configuration' : 'Timeframe'">
                            <n-select
                                v-model:value="form.timeframe"
                                :options="timeframeOptions"
                                :disabled="isAccumulation"
                            />
                        </n-form-item>
                        <n-form-item label="Date range" class="date-range-item">
                            <n-date-picker
                                v-model:value="dateRange"
                                type="datetimerange"
                                clearable
                            >
                                <template #separator>
                                    <n-icon><CalendarOutline /></n-icon>
                                </template>
                            </n-date-picker>
                        </n-form-item>
                    </div>

                    <div v-if="!isAccumulation" class="control-grid two">
                        <n-form-item label="Base order">
                            <n-input-number
                                v-accessible-stepper="'Base order'"
                                v-model:value="form.baseOrderSize"
                                :min="1"
                                :precision="2"
                            />
                        </n-form-item>
                        <n-form-item label="Take profit %">
                            <n-input-number
                                v-accessible-stepper="'Take profit'"
                                v-model:value="form.takeProfitPct"
                                :min="0"
                                :precision="2"
                            />
                        </n-form-item>
                        <n-form-item label="Stop loss %">
                            <n-input-number
                                v-accessible-stepper="'Stop loss'"
                                v-model:value="form.stopLossPct"
                                :min="0"
                                :precision="2"
                                clearable
                                placeholder="Disabled"
                            />
                        </n-form-item>
                    </div>

                     <div v-if="!isAccumulation" class="control-grid two">
                          <n-form-item label="Max safety orders">
                            <n-input-number
                                v-accessible-stepper="'Max safety orders'"
                                v-model:value="form.maxSafetyOrders"
                                :min="0"
                                :precision="0"
                            />
                        </n-form-item>
                        <n-form-item label="Safety step %">
                            <n-input-number
                                v-accessible-stepper="'Safety step'"
                                v-model:value="form.safetyOrderStepPct"
                                :min="0.1"
                                :precision="2"
                            />
                        </n-form-item>
                    </div>

                    <template v-if="isAccumulation">
                        <n-form-item label="Initial funding"><n-input-number v-accessible-stepper="'Initial funding'" v-model:value="form.funding" :min="1" :input-props="{ 'aria-label': 'Initial funding' }" /></n-form-item>
                        <n-form-item label="Adverse buy slippage · basis points"><n-input-number v-accessible-stepper="'Adverse buy slippage'" v-model:value="form.slippageBps" :min="0" :max="1000" :input-props="{ 'aria-label': 'Adverse buy slippage' }" /></n-form-item>
                        <n-form-item label="Fixed DCA comparison interval · candles"><n-input-number v-accessible-stepper="'Fixed DCA comparison interval'" v-model:value="form.fixedIntervalCandles" :min="1" :max="20000" :precision="0" :input-props="{ 'aria-label': 'Fixed DCA comparison interval' }" /></n-form-item>
                    </template>
                    <n-form-item label="Fee">
                        <n-input-number
                            v-accessible-stepper="'Fee'"
                            v-model:value="form.fee"
                            :min="0"
                            :step="0.0001"
                            :precision="4"
                        />
                    </n-form-item>
                </n-form>

                <div class="action-row">
                    <n-button
                        attr-type="submit"
                        type="primary"
                        :loading="isRunning"
                        :disabled="!canRun"
                    >
                        <template #icon>
                            <n-icon><PlayCircleOutline /></n-icon>
                        </template>
                        Run
                    </n-button>
                    <n-button secondary @click="resetResult">
                        <template #icon>
                            <n-icon><RefreshOutline /></n-icon>
                        </template>
                        Reset
                    </n-button>
                </div>
            </form>

            <div class="backtest-results dashboard-panel ledger-panel chart-panel">
                <n-alert
                    v-if="errorMessage"
                    type="error"
                    :show-icon="false"
                    class="result-alert"
                >
                    {{ errorMessage }}
                </n-alert>

                <div v-if="!hasResult" class="empty-result">
                    <n-icon size="28"><FlaskOutline /></n-icon>
                    <span>Awaiting replay</span>
                </div>

                <template v-else-if="result">
                    <div class="stats-grid" :class="{ 'accumulation-stats': result.accumulation }" aria-label="Backtest stats">
                        <div
                            v-for="tile in statTiles"
                            :key="tile.label"
                            class="stat-tile"
                            :class="tile.tone ? `stat-${tile.tone}` : ''"
                        >
                            <span>{{ tile.label }}</span>
                            <strong>{{ tile.value }}</strong>
                        </div>
                    </div>

                    <div
                        v-if="comparison"
                        class="comparison-strip"
                        :class="`comparison-${comparisonTone}`"
                    >
                        <span>Previous run</span>
                        <strong>{{ formatBacktestDelta(comparison.profitDelta) }}</strong>
                        <span>{{ formatBacktestDelta(comparison.winRateDelta, '%') }} win rate</span>
                        <span>{{ formatBacktestDelta(comparison.tradesDelta, '') }} trades</span>
                    </div>

                    <n-alert v-if="result.accumulation?.trades_truncated" type="info">Chart markers and the trade list show the first 100 buys. Summary and comparison include every modeled buy.</n-alert>
                    <p v-if="result.accumulation">{{ result.accumulation.gap_count }} gaps · Strategy simulation; no live orders or automatic sale at the end.</p>
                    <BacktestResultChart
                        :candles="result.chart.candles"
                        :markers="result.chart.markers"
                        :indicators="result.chart.indicators ?? []"
                    />

                    <n-tabs
                        class="calm-tabs backtest-result-tabs"
                        type="line"
                        animated
                        :tabs-padding="20"
                    >
                        <n-tab-pane name="trades" tab="Trades">
                            <n-data-table
                                :columns="result.accumulation ? accumulationTradeColumns : tradeColumns"
                                :data="result.accumulation ? result.accumulation.accumulation_trades : result.trades"
                                :scroll-x="result.accumulation ? 780 : undefined"
                                :bordered="false"
                                size="small"
                            />
                        </n-tab-pane>
                        <n-tab-pane v-if="result.accumulation" name="comparison" tab="Comparison">
                            <p>Equal initial funding · quote amounts include modeled buy fees. Ending value includes cash and unsold coins before future sale fees.</p>
                            <n-data-table :columns="accumulationComparisonColumns" :data="result.accumulation.results" :scroll-x="950" :bordered="false" size="small" />
                        </n-tab-pane>
                        <n-tab-pane name="metadata" tab="Run">
                            <dl class="metadata-grid">
                                <div>
                                    <dt>Symbol</dt>
                                    <dd>{{ result.stats.symbol }}</dd>
                                </div>
                                <div>
                                    <dt>Strategy</dt>
                                    <dd>{{ result.stats.strategy }}</dd>
                                </div>
                                 <div>
                                     <dt>Trade mode</dt>
                                     <dd>{{ result.stats.trade_mode === 'accumulation' ? 'Accumulation' : 'Dynamic DCA' }}</dd>
                                 </div>
                                 <div>
                                     <dt>Timeframe</dt>
                                     <dd>{{ result.stats.timeframe }}</dd>
                                 </div>
                                <div>
                                    <dt>Candles fetched</dt>
                                    <dd>{{ result.stats.candles_fetched }}</dd>
                                </div>
                                <div>
                                    <dt>Warmup candles</dt>
                                    <dd>{{ result.stats.warmup_candles ?? 0 }}</dd>
                                </div>
                            </dl>
                        </n-tab-pane>
                    </n-tabs>
                    <template v-if="result.accumulation">
                        <p v-for="caveat in result.accumulation.caveats" :key="caveat" class="run-caveat">{{ caveat }}</p>
                    </template>
                </template>
            </div>
        </section>
    </div>
</template>

<style scoped>
.backtest-page {
    gap: 12px;
}

.backtest-workspace {
    display: grid;
    grid-template-columns: minmax(320px, 380px) minmax(0, 1fr);
    gap: 12px;
    align-items: start;
}

.backtest-controls,
.backtest-results {
    min-width: 0;
    padding: 16px;
}

.backtest-controls {
    position: sticky;
    top: 12px;
}

.panel-title-row {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 14px;
    color: var(--mw-color-text-primary);
}

.panel-title-row h2 {
    margin: 0;
    font-size: 1rem;
    font-weight: 600;
}

.backtest-form {
    display: grid;
    gap: 14px;
}

.control-grid {
    display: grid;
    gap: 14px 12px;
}

.control-grid.two {
    grid-template-columns: repeat(2, minmax(0, 1fr));
}

.numeric-grid {
    align-items: start;
}

.date-range-item {
    grid-column: 1 / -1;
}

.backtest-controls :deep(.n-date-picker),
.backtest-controls :deep(.n-input-number) {
    width: 100%;
}

.backtest-controls :deep(.n-form-item-label) {
    min-height: 24px;
    padding: 0 0 6px 2px;
    line-height: 1.25;
}

.symbol-picker {
    width: 100%;
}

.symbol-fallback-input {
    margin-top: 8px;
}

.action-row {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    margin-top: 14px;
}

.result-alert {
    margin-bottom: 12px;
}

.empty-result {
    display: grid;
    min-height: 320px;
    place-items: center;
    align-content: center;
    gap: 10px;
    color: var(--mw-color-text-muted);
    font-weight: 450;
}

.stats-grid {
    display: grid;
    grid-template-columns: repeat(6, minmax(0, 1fr));
    gap: 8px;
    margin-bottom: 12px;
}

.stats-grid.accumulation-stats { grid-template-columns: repeat(3, minmax(0, 1fr)); }

.stat-tile {
    min-width: 0;
    padding: 10px 12px;
    border: 1px solid var(--mw-color-border);
    border-radius: var(--mw-radius-sm);
    background: var(--mw-surface-card-subtle);
}

.stat-tile span {
    display: block;
    color: var(--mw-color-text-muted);
    font-size: 0.78rem;
    font-weight: 450;
}

.stat-tile strong {
    display: block;
    overflow-wrap: anywhere;
    color: var(--mw-color-text-primary);
    font-family: var(--mw-font-mono);
    font-size: 1rem;
    font-weight: 500;
}

.stat-positive strong {
    color: var(--mw-color-success);
}

.stat-negative strong {
    color: var(--mw-color-error);
}

.stat-warning strong {
    color: var(--mw-color-warning);
}

.comparison-strip {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 10px;
    margin-bottom: 12px;
    padding: 10px 12px;
    border: 1px solid var(--mw-color-border);
    border-radius: var(--mw-radius-sm);
    background: var(--mw-surface-card-muted);
    color: var(--mw-color-text-secondary);
}

.comparison-strip strong {
    font-family: var(--mw-font-mono);
    font-weight: 500;
}

.comparison-positive strong {
    color: var(--mw-color-success);
}

.comparison-negative strong {
    color: var(--mw-color-error);
}

.metadata-grid {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 12px;
    margin: 0;
}

.metadata-grid div {
    min-width: 0;
}

.metadata-grid dt {
    color: var(--mw-color-text-muted);
    font-size: 0.78rem;
    font-weight: 450;
}

.metadata-grid dd {
    margin: 2px 0 0;
    overflow-wrap: anywhere;
    color: var(--mw-color-text-primary);
    font-family: var(--mw-font-mono);
    font-size: 0.9rem;
}

@media (max-width: 980px) {
    .backtest-workspace {
        grid-template-columns: 1fr;
    }

    .backtest-controls {
        position: static;
    }

    .stats-grid {
        grid-template-columns: repeat(3, minmax(0, 1fr));
    }
}

@media (max-width: 640px) {
    .control-grid.two,
    .stats-grid.accumulation-stats,
    .stats-grid,
    .metadata-grid {
        grid-template-columns: 1fr;
    }
}
</style>
