<template>
    <div class="statistics-shell">
        <section class="portfolio-card" aria-labelledby="portfolio-exposure-title">
                <div class="stat-heading">
                    <h2 id="portfolio-exposure-title">Portfolio exposure</h2>
                    <p>Free quote and capital committed to open deals</p>
                </div>
                <div class="profit-summary">
                    <div class="profit-label">Net profit &amp; loss</div>
                    <n-statistic :class="hasStatisticsData ? profit_class : undefined" :value="hasStatisticsData ? formatFixed2(profit_overall) : 'Unavailable'" />
                    <div v-if="hasStatisticsData" class="stat-detail">Realized {{ formatFixed2(profit_overall - upnl) }} · Unrealized {{ formatFixed2(upnl) }}</div>
                </div>
                <template v-if="exposure">
                    <template v-if="budgetAllocation">
                        <div class="budget-heading"><span>Budget allocation</span><strong>{{ formatFixed2(budgetAllocation.limit) }} {{ quote_currency }} capital budget</strong></div>
                        <div class="budget-subheading">{{ budgetAllocation.usedPercent }}% committed to deals and reserves<span v-if="budgetAllocation.exceeded"> · Over budget</span></div>
                        <div class="exposure-track" role="img" :aria-label="`${formatFixed2(budgetAllocation.limit)} ${quote_currency} capital budget: ${formatFixed2(budgetAllocation.locked)} in deals, ${formatFixed2(budgetAllocation.reserved)} reserved, ${formatFixed2(budgetAllocation.tradable)} available to trade`">
                            <span class="exposure-locked" :style="{ width: `${budgetAllocation.lockedPercent}%` }" />
                            <span class="exposure-reserved" :style="{ width: `${budgetAllocation.reservedPercent}%` }" />
                            <span class="exposure-tradable" :style="{ width: `${budgetAllocation.tradablePercent}%` }" />
                        </div>
                        <div class="exposure-legend">
                            <span><i class="legend-key is-locked" aria-hidden="true" />Funds in deals <strong>{{ formatFixed2(budgetAllocation.locked) }} {{ quote_currency }}</strong></span>
                            <span><i class="legend-key is-reserved" aria-hidden="true" />Reserved for open and pending orders <strong>{{ formatFixed2(budgetAllocation.reserved) }} {{ quote_currency }}</strong></span>
                            <span><i class="legend-key is-tradable" aria-hidden="true" />Available to trade <strong>{{ formatFixed2(budgetAllocation.tradable) }} {{ quote_currency }}</strong></span>
                        </div>
                    </template>
                    <p v-else class="budget-unavailable" role="status">{{ budgetMessage }}</p>
                    <div class="exposure-totals"><span>Exchange free <strong>{{ formatFixed2(exposure.available) }} {{ quote_currency }}</strong></span><span v-if="budgetAllocation">Outside available to trade <strong>{{ formatFixed2(budgetAllocation.otherExchangeFree) }} {{ quote_currency }}</strong></span><span>Portfolio value <strong>{{ portfolio_value === null ? 'Unavailable' : formatFixed2(portfolio_value) }} {{ quote_currency }}</strong></span></div>
                </template>
                <p v-else class="exposure-unavailable" role="status">Waiting for live balances</p>
        </section>
    </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useWebSocketDataStore } from '../stores/websocket'
import { storeToRefs } from 'pinia'
import { useSharedConfigSnapshot } from '../control-center/configSnapshotStore'
import { resolveBudgetAllocation } from '../helpers/portfolioExposure'
const statistics_store = useWebSocketDataStore("statistics")
const statistics_data = storeToRefs(statistics_store)
const configSnapshotStore = useSharedConfigSnapshot()
const hasStatisticsData = computed(() => statistics_data.hasReceivedData.value)
const profit_overall = ref(0)
const profit_class = ref<'green' | 'red'>('green')
const upnl = ref(0)
const funds_locked = ref(0)
const funds_available = ref<number | null>(null)
const funds_tradable = ref<number | null>(null)
const capital_budget = ref<number | null>(null)
const capital_locked = ref<number | null>(null)
const capital_reserve = ref<number | null>(null)
const capital_pending = ref<number | null>(null)
const capital_budget_reason = ref<string | null>(null)
const portfolio_value = computed(() =>
    funds_available.value === null
        ? null
        : Math.max(0, funds_available.value + funds_locked.value + upnl.value),
)
const exposure = computed(() => {
    const available = funds_available.value
    if (available === null) return null
    const free = Math.max(0, available)
    return { available: free }
})
const budgetAllocation = computed(() => exposure.value === null ? null : resolveBudgetAllocation({
    effectiveBudget: capital_budget.value,
    fundsLocked: capital_locked.value,
    openTradeReserve: capital_reserve.value,
    pendingQuote: capital_pending.value,
    tradableQuote: funds_tradable.value,
    exchangeFree: exposure.value.available,
    reason: capital_budget_reason.value,
}))
const budgetMessage = computed(() => capital_budget_reason.value === 'capital_budget_unconfigured'
    ? 'Capital budget is not configured.'
    : 'Capital budget allocation is unavailable.')
const quote_currency = computed(() =>
    String(configSnapshotStore.snapshot.value?.currency ?? '').toUpperCase(),
)

// Get new statistics data
watch(statistics_data.data, (newData) => {
    if (newData !== undefined && newData !== null) {
        const websocket_data = newData as any
        upnl.value = toNumberOrZero(websocket_data.upnl)
        profit_overall.value = toNumberOrZero(websocket_data.profit_overall)
        profit_class.value = row_classes(profit_overall.value)
        funds_locked.value = toNumberOrZero(websocket_data.funds_locked)
        funds_available.value = toOptionalNumber(websocket_data.funds_available)
        capital_budget.value = toOptionalNumber(websocket_data.capital_effective_max_fund)
        capital_locked.value = toOptionalNumber(websocket_data.capital_funds_locked)
        capital_reserve.value = toOptionalNumber(websocket_data.capital_open_trade_reserve)
        capital_pending.value = toOptionalNumber(websocket_data.capital_pending_quote)
        capital_budget_reason.value = typeof websocket_data.capital_budget_reason === 'string'
            ? websocket_data.capital_budget_reason : null
        const capitalAvailable = toOptionalNumber(websocket_data.capital_available_quote)
        const reportedTradable = toOptionalNumber(websocket_data.funds_tradable)
        funds_tradable.value = funds_available.value === null
            ? null
            : Math.min(
                Math.max(0, funds_available.value),
                Math.max(0, reportedTradable ?? (
                    capitalAvailable === null || websocket_data.capital_budget_reason === 'capital_budget_unconfigured'
                        ? funds_available.value : capitalAvailable
                )),
            )
    }

}, { immediate: true })

function row_classes(data: number): 'green' | 'red' {
    if (Math.sign(data) >= 0) {
        return 'green'
    } else {
        return 'red'
    }
}

function toNumberOrZero(value: unknown): number {
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : 0
}

function toOptionalNumber(value: unknown): number | null {
    if (value === null || value === undefined) {
        return null
    }
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : null
}

function formatFixed2(value: number): string {
    return value.toFixed(2)
}

</script>

<style scoped>
.statistics-shell { height: 100%; }
.portfolio-card {
    display: flex;
    flex-direction: column;
    min-width: 0;
    min-height: 320px;
    height: 100%;
    padding: 19px 20px;
    border: 1px solid var(--mw-color-border);
    border-radius: var(--mw-radius-md, 10px);
    background: var(--mw-color-surface-panel);
}
.stat-heading h2 {
    margin: 0;
    color: var(--mw-color-text-primary);
    font-size: 14px;
    font-weight: 600;
}
.stat-heading p { margin: 5px 0 0; color: var(--mw-color-text-muted); font-size: 11px; }
.profit-summary { margin-top: 20px; }
.profit-label { margin-bottom: 8px; color: var(--mw-color-text-primary); font-size: 13px; font-weight: 600; }
.stat-detail,
.exposure-unavailable { color: var(--mw-color-text-muted); font-size: 11px; line-height: 1.35; }
.stat-detail { margin-top: 5px; }
:deep(.n-statistic-value) {
    color: var(--mw-color-text-primary);
    font-family: var(--mw-font-mono);
    font-size: clamp(21px, 2vw, 29px);
    font-variant-numeric: tabular-nums;
    font-weight: 600;
    line-height: 1.15;
}
:deep(.n-statistic-value__content) { font-weight: 600; }
.green { --n-value-text-color: var(--mw-color-success) !important; }
.red { --n-value-text-color: var(--mw-color-error) !important; }
.budget-heading {
    display: flex;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 6px;
    margin-top: auto;
    padding-top: 24px;
    color: var(--mw-color-text-muted);
    font-size: 11px;
}
.budget-heading strong { color: var(--mw-color-text-primary); font-weight: 600; }
.budget-subheading { margin-top: 4px; color: var(--mw-color-text-muted); font-size: 11px; }
.budget-unavailable { margin: auto 0 0; padding-top: 24px; color: var(--mw-color-text-muted); font-size: 11px; }
.exposure-track {
    display: flex;
    height: 17px;
    margin-top: 10px;
    overflow: hidden;
    border-radius: 9px;
    background: var(--mw-surface-card-muted);
}
.exposure-track > span { height: 100%; min-width: 0; }
.exposure-locked { background: var(--mw-color-primary); }
.exposure-reserved { background: var(--mw-color-warning); }
.exposure-tradable { background: var(--mw-color-info); }
.exposure-legend { display: grid; gap: 8px; margin-top: 16px; }
.exposure-legend > span {
    display: flex;
    align-items: center;
    gap: 7px;
    min-width: 0;
    color: var(--mw-color-text-muted);
    font-size: 11px;
}
.exposure-legend strong,
.exposure-totals strong { margin-left: auto; color: var(--mw-color-text-primary); font-weight: 600; white-space: nowrap; }
.legend-key { flex: none; width: 8px; height: 8px; border-radius: 2px; }
.legend-key.is-locked { background: var(--mw-color-primary); }
.legend-key.is-reserved { background: var(--mw-color-warning); }
.legend-key.is-tradable { background: var(--mw-color-info); }
.exposure-totals {
    display: grid;
    gap: 7px;
    margin-top: 15px;
    padding-top: 12px;
    border-top: 1px solid var(--mw-color-border);
}
.exposure-totals span { display: flex; gap: 10px; color: var(--mw-color-text-muted); font-size: 11px; }
.exposure-unavailable { margin: auto 0 0; padding-top: 24px; }
@media (max-width: 767px) {
    .portfolio-card { min-height: 300px; padding: 16px; }
}
</style>
