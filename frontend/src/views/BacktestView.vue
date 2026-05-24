<script setup lang="ts">
import { computed, h, onMounted, reactive, ref } from 'vue'
import type { DataTableColumns, SelectOption } from 'naive-ui'
import {
    CalendarOutline,
    FlaskOutline,
    PlayCircleOutline,
    RefreshOutline,
} from '@vicons/ionicons5'

import { fetchJson } from '../api/client'
import BacktestResultChart from '../components/BacktestResultChart.vue'
import { extractApiErrorMessage } from '../helpers/apiErrors'
import {
    BACKTEST_TIMEFRAME_OPTIONS,
    BACKTEST_TRADE_MODE_OPTIONS,
    buildBacktestRequest,
    computeBacktestComparison,
    createDefaultBacktestForm,
    createDefaultBacktestRange,
    formatBacktestDelta,
    formatBacktestNumber,
    getBacktestSummary,
    type BacktestFormState,
    type BacktestResult,
    type BacktestTrade,
} from '../helpers/backtest'

interface StrategyListResponse {
    strategies?: Array<{
        slug: string
        name?: string
    }>
}

const form = reactive<BacktestFormState>(createDefaultBacktestForm())
const dateRange = ref<[number, number] | null>(createDefaultBacktestRange())
const result = ref<BacktestResult | null>(null)
const previousResult = ref<BacktestResult | null>(null)
const isRunning = ref(false)
const isLoadingStrategies = ref(false)
const errorMessage = ref('')
const strategyOptions = ref<SelectOption[]>([])
const lastRunAt = ref<number | null>(null)

const timeframeOptions = BACKTEST_TIMEFRAME_OPTIONS.map((option) => ({ ...option }))
const tradeModeOptions = BACKTEST_TRADE_MODE_OPTIONS.map((option) => ({ ...option }))
const isSidestepMode = computed(() => form.tradeMode === 'sidestep')

const canRun = computed(() => {
    if (!dateRange.value) {
        return false
    }
    const hasStrategy = isSidestepMode.value
        ? form.sidestepBearishStrategySlug.trim().length > 0 &&
          form.sidestepReentryStrategySlug.trim().length > 0
        : form.strategySlug.trim().length > 0
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

const statTiles = computed(() => [
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
        title: 'Entry',
        key: 'open_price',
        width: 120,
        render(row) {
            return formatBacktestNumber(row.open_price, 6)
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

const lastRunLabel = computed(() =>
    lastRunAt.value ? new Date(lastRunAt.value).toLocaleString() : 'No run yet',
)

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
})
</script>

<template>
    <div class="page-shell backtest-page">
        <section class="backtest-hero mw-shell-card" aria-labelledby="backtest-title">
            <div class="backtest-hero-copy">
                <n-text depth="3" class="backtest-kicker">Backtest</n-text>
                <h1 id="backtest-title">Strategy replay</h1>
            </div>
            <div class="backtest-status" aria-live="polite">
                <span class="status-dot" :class="{ 'status-dot-running': isRunning }" />
                <span>{{ statusText }}</span>
                <span class="status-muted">{{ lastRunLabel }}</span>
            </div>
        </section>

        <section class="backtest-workspace">
            <form class="backtest-controls mw-shell-card" @submit.prevent="runBacktest">
                <div class="panel-title-row">
                    <n-icon size="18"><FlaskOutline /></n-icon>
                    <h2>Run setup</h2>
                </div>

                <n-form label-placement="top" :show-feedback="false">
                    <n-form-item label="Symbol">
                        <n-input
                            v-model:value="form.symbol"
                            placeholder="BTC/USDT"
                            autocomplete="off"
                        />
                    </n-form-item>

                    <n-form-item v-if="!isSidestepMode" label="Strategy">
                        <n-select
                            v-if="strategyOptions.length > 0"
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

                    <n-form-item label="Trade mode">
                        <n-radio-group
                            v-model:value="form.tradeMode"
                            class="trade-mode-selector"
                        >
                            <n-radio-button
                                v-for="option in tradeModeOptions"
                                :key="option.value"
                                :value="option.value"
                            >
                                {{ option.label }}
                            </n-radio-button>
                        </n-radio-group>
                    </n-form-item>

                    <div v-if="isSidestepMode" class="control-grid two">
                        <n-form-item label="Bearish sidestep strategy">
                            <n-select
                                v-if="strategyOptions.length > 0"
                                v-model:value="form.sidestepBearishStrategySlug"
                                filterable
                                :loading="isLoadingStrategies"
                                :options="strategyOptions"
                            />
                            <n-input
                                v-else
                                v-model:value="form.sidestepBearishStrategySlug"
                                placeholder="ema_down"
                                autocomplete="off"
                            />
                        </n-form-item>
                        <n-form-item label="Re-entry strategy">
                            <n-select
                                v-if="strategyOptions.length > 0"
                                v-model:value="form.sidestepReentryStrategySlug"
                                filterable
                                :loading="isLoadingStrategies"
                                :options="strategyOptions"
                            />
                            <n-input
                                v-else
                                v-model:value="form.sidestepReentryStrategySlug"
                                placeholder="ema20_swing_reverse"
                                autocomplete="off"
                            />
                        </n-form-item>
                    </div>

                    <div class="control-grid two">
                        <n-form-item label="Timeframe">
                            <n-select
                                v-model:value="form.timeframe"
                                :options="timeframeOptions"
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

                    <div class="control-grid two">
                        <n-form-item label="Base order">
                            <n-input-number
                                v-model:value="form.baseOrderSize"
                                :min="1"
                                :precision="2"
                            />
                        </n-form-item>
                        <n-form-item label="Take profit %">
                            <n-input-number
                                v-model:value="form.takeProfitPct"
                                :min="0"
                                :precision="2"
                            />
                        </n-form-item>
                        <n-form-item label="Stop loss %">
                            <n-input-number
                                v-model:value="form.stopLossPct"
                                :min="0"
                                :precision="2"
                            />
                        </n-form-item>
                        <n-form-item label="Max safety orders">
                            <n-input-number
                                v-model:value="form.maxSafetyOrders"
                                :min="0"
                                :precision="0"
                            />
                        </n-form-item>
                        <n-form-item label="Safety step %">
                            <n-input-number
                                v-model:value="form.safetyOrderStepPct"
                                :min="0.1"
                                :precision="2"
                            />
                        </n-form-item>
                        <n-form-item label="Step scale">
                            <n-input-number
                                v-model:value="form.stepScale"
                                :min="0.1"
                                :precision="2"
                            />
                        </n-form-item>
                    </div>

                    <n-form-item label="Fee">
                        <n-input-number
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

            <div class="backtest-results mw-shell-card">
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
                    <div class="stats-grid" aria-label="Backtest stats">
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

                    <BacktestResultChart
                        :candles="result.chart.candles"
                        :markers="result.chart.markers"
                    />

                    <n-tabs type="line" animated>
                        <n-tab-pane name="trades" tab="Trades">
                            <n-data-table
                                :columns="tradeColumns"
                                :data="result.trades"
                                :bordered="false"
                                :single-line="false"
                                size="small"
                            />
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
                                    <dd>
                                        {{
                                            result.stats.trade_mode === 'sidestep'
                                                ? 'Sidestep'
                                                : 'Dynamic DCA'
                                        }}
                                    </dd>
                                </div>
                                <div v-if="result.stats.trade_mode === 'sidestep'">
                                    <dt>Bearish strategy</dt>
                                    <dd>{{ result.stats.sidestep_bearish_strategy }}</dd>
                                </div>
                                <div v-if="result.stats.trade_mode === 'sidestep'">
                                    <dt>Re-entry strategy</dt>
                                    <dd>{{ result.stats.sidestep_reentry_strategy }}</dd>
                                </div>
                                <div>
                                    <dt>Timeframe</dt>
                                    <dd>{{ result.stats.timeframe }}</dd>
                                </div>
                                <div>
                                    <dt>Candles fetched</dt>
                                    <dd>{{ result.stats.candles_fetched }}</dd>
                                </div>
                            </dl>
                        </n-tab-pane>
                    </n-tabs>
                </template>
            </div>
        </section>
    </div>
</template>

<style scoped>
.backtest-page {
    gap: 16px;
}

.backtest-hero {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    padding: 18px 20px;
    border: 1px solid rgba(29, 92, 73, 0.14);
    border-radius: var(--mw-radius-md);
}

.backtest-hero-copy {
    display: flex;
    min-width: 0;
    flex-direction: column;
    gap: 2px;
}

.backtest-kicker {
    font-size: 0.85rem;
    font-weight: 700;
    text-transform: uppercase;
}

.backtest-hero h1 {
    margin: 0;
    font-size: 2rem;
    line-height: 1.1;
}

.backtest-status {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    min-height: 36px;
    color: var(--mw-color-text-secondary);
    font-weight: 700;
}

.status-dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    background: var(--mw-color-success);
}

.status-dot-running {
    background: var(--mw-color-warning);
}

.status-muted {
    color: var(--mw-color-text-muted);
    font-family: var(--mw-font-mono);
    font-size: 0.78rem;
    font-weight: 500;
}

.backtest-workspace {
    display: grid;
    grid-template-columns: minmax(280px, 360px) minmax(0, 1fr);
    gap: 16px;
    align-items: start;
}

.backtest-controls,
.backtest-results {
    min-width: 0;
    padding: 16px;
    border: 1px solid rgba(29, 92, 73, 0.14);
    border-radius: var(--mw-radius-md);
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
    font-size: 1.25rem;
}

.control-grid {
    display: grid;
    gap: 12px;
}

.control-grid.two {
    grid-template-columns: repeat(2, minmax(0, 1fr));
}

.date-range-item {
    grid-column: 1 / -1;
}

.backtest-controls :deep(.n-date-picker),
.backtest-controls :deep(.n-input-number) {
    width: 100%;
}

.trade-mode-selector {
    display: flex;
    width: 100%;
}

.trade-mode-selector :deep(.n-radio-button) {
    flex: 1 1 0;
    text-align: center;
}

.action-row {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    margin-top: 4px;
}

.result-alert {
    margin-bottom: 12px;
}

.empty-result {
    display: grid;
    min-height: 520px;
    place-items: center;
    align-content: center;
    gap: 10px;
    color: var(--mw-color-text-muted);
    font-weight: 700;
}

.stats-grid {
    display: grid;
    grid-template-columns: repeat(6, minmax(0, 1fr));
    gap: 8px;
    margin-bottom: 12px;
}

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
    font-weight: 700;
}

.stat-tile strong {
    display: block;
    overflow-wrap: anywhere;
    color: var(--mw-color-text-primary);
    font-family: var(--mw-font-mono);
    font-size: 1rem;
    font-weight: 700;
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
    font-weight: 700;
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
    font-weight: 700;
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
    .backtest-hero {
        align-items: flex-start;
        flex-direction: column;
    }

    .backtest-hero h1 {
        font-size: 1.55rem;
    }

    .control-grid.two,
    .stats-grid,
    .metadata-grid {
        grid-template-columns: 1fr;
    }
}
</style>
