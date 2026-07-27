<template>
    <TradeReplayChart
        v-if="chartReady"
        class="waiting-replay-chart"
        :symbol="props.rowData.symbol"
        :precision="Number(props.rowData.precision ?? 0)"
        :start-timestamp="replayStartTimestamp"
        :deal-id="props.rowData.deal_id"
        :campaign-id="campaignId"
        :min-timeframe="props.minTimeframe"
        :markers="chartMarkers"
        :price-lines="chartPriceLines"
    />
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { fetchJson } from '../api/client'
import type { TimeframeChoice } from '../helpers/openTrades'
import type {
    TradeExecutionRow,
    WaitingCampaignRow,
} from '../stores/trades'
import TradeReplayChart from './TradeReplayChart.vue'

const props = defineProps<{
    rowData: WaitingCampaignRow
    minTimeframe: TimeframeChoice
}>()

const BUY_MARKER_COLOR = '#2E7D5B'
const BUY_LINE_COLOR = '#1D5C49'
const SELL_MARKER_COLOR = '#B4443F'

function normalizeUuid(value: string | null | undefined): string | null {
    const normalized = String(value ?? '').trim()
    return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(
        normalized,
    )
        ? normalized
        : null
}

const campaignId = computed(() => normalizeUuid(props.rowData.campaign_id))
const replayIdentity = computed(
    () => props.rowData.deal_id ?? campaignId.value,
)
const executions = ref<TradeExecutionRow[]>([])
const executionHistoryResolved = ref(!replayIdentity.value)
const chartReady = computed(() => executionHistoryResolved.value)

function executionTimestampMs(timestamp: string): number {
    const numericTimestamp = Number(timestamp)
    return Number.isFinite(numericTimestamp)
        ? numericTimestamp
        : Date.parse(timestamp)
}

const sortedExecutions = computed(() =>
    [...executions.value].sort(
        (left, right) =>
            executionTimestampMs(left.timestamp) -
            executionTimestampMs(right.timestamp),
    ),
)
const replayStartTimestamp = computed(
    () =>
        sortedExecutions.value[0]?.timestamp ??
        props.rowData.campaign_started_at ??
        props.rowData.open_date ??
        props.rowData.last_transition_at ??
        Date.now(),
)

function countExecutionsUntil(
    endIndex: number,
    matcher: (execution: TradeExecutionRow) => boolean,
): number {
    let count = 0
    for (let index = 0; index <= endIndex; index += 1) {
        if (matcher(sortedExecutions.value[index])) {
            count += 1
        }
    }
    return count
}

function getBuyLineTitle(
    execution: TradeExecutionRow,
    index: number,
): string {
    if (execution.role === 'manual_buy') {
        return 'MANUAL'
    }
    if (execution.role === 'base_order') {
        const reentryIndex = countExecutionsUntil(
            index,
            (candidate) =>
                candidate.side === 'buy' &&
                candidate.role === 'base_order',
        )
        return reentryIndex <= 1 ? 'BO' : `RE${reentryIndex - 1}`
    }
    const orderCount = Number(execution.order_count)
    if (Number.isFinite(orderCount) && orderCount > 0) {
        return `SO${orderCount}`
    }
    const buyIndex = countExecutionsUntil(
        index,
        (candidate) => candidate.side === 'buy',
    )
    return `SO${Math.max(1, buyIndex - 1)}`
}

const chartMarkers = computed(() => {
    if (sortedExecutions.value.length === 0) {
        const exitTimestamp = props.rowData.last_transition_at
        if (!exitTimestamp) {
            return []
        }
        const exitPrice = Number(props.rowData.waiting_reference_price)
        const hasExactExitPrice =
            Number.isFinite(exitPrice) && exitPrice > 0
        return [
            {
                timestamp: exitTimestamp,
                position: hasExactExitPrice
                    ? ('atPriceMiddle' as const)
                    : ('aboveBar' as const),
                ...(hasExactExitPrice ? { price: exitPrice } : {}),
                color: SELL_MARKER_COLOR,
                shape: 'arrowDown' as const,
                text: 'Exit',
            },
        ]
    }

    return sortedExecutions.value.map((execution, index) => {
        if (execution.side === 'buy') {
            const baseOrderIndex = countExecutionsUntil(
                index,
                (candidate) =>
                    candidate.side === 'buy' &&
                    candidate.role === 'base_order',
            )
            return {
                timestamp: execution.timestamp,
                position: 'belowBar' as const,
                color: BUY_MARKER_COLOR,
                shape: 'arrowUp' as const,
                text:
                    execution.role === 'base_order' &&
                    baseOrderIndex > 1
                        ? 'Re-entry'
                        : 'Buy',
            }
        }

        const exitPrice = Number(execution.price)
        const hasExactExitPrice =
            Number.isFinite(exitPrice) && exitPrice > 0
        return {
            timestamp: execution.timestamp,
            position: hasExactExitPrice
                ? ('atPriceMiddle' as const)
                : ('aboveBar' as const),
            ...(hasExactExitPrice ? { price: exitPrice } : {}),
            color: SELL_MARKER_COLOR,
            shape: 'arrowDown' as const,
            text: 'Exit',
        }
    })
})

const chartPriceLines = computed(() => {
    if (sortedExecutions.value.length === 0) {
        const exitPrice = Number(props.rowData.waiting_reference_price)
        return Number.isFinite(exitPrice) && exitPrice > 0
            ? [
                  {
                      price: exitPrice,
                      color: SELL_MARKER_COLOR,
                      lineStyle: 3 as const,
                      title: 'EXIT',
                  },
              ]
            : []
    }

    return sortedExecutions.value.flatMap((execution, index) => {
        const price = Number(execution.price)
        if (!Number.isFinite(price) || price <= 0) {
            return []
        }
        if (execution.side === 'buy') {
            return [
                {
                    price,
                    color: BUY_LINE_COLOR,
                    lineStyle: 2 as const,
                    title: getBuyLineTitle(execution, index),
                },
            ]
        }
        const exitIndex = countExecutionsUntil(
            index,
            (candidate) => candidate.side === 'sell',
        )
        return [
            {
                price,
                color: SELL_MARKER_COLOR,
                lineStyle: 3 as const,
                title: `EXIT${exitIndex}`,
            },
        ]
    })
})

async function loadExecutions(): Promise<void> {
    if (!replayIdentity.value) {
        executionHistoryResolved.value = true
        return
    }
    const campaignQuery = campaignId.value
        ? `?campaign_id=${encodeURIComponent(campaignId.value)}`
        : ''
    try {
        const dealExecutionsUrl =
            `/trades/executions/${props.rowData.deal_id}`
        const executionUrl = props.rowData.deal_id
            ? dealExecutionsUrl
            : `/trades/executions/${replayIdentity.value}`
        const response = await fetchJson<{ result: TradeExecutionRow[] }>(
            `${executionUrl}${campaignQuery}`,
        )
        executions.value = Array.isArray(response.result)
            ? response.result
            : []
    } catch (_error) {
        executions.value = []
    } finally {
        executionHistoryResolved.value = true
    }
}

onMounted(() => {
    void loadExecutions()
})
</script>

<style scoped>
.waiting-replay-chart {
    min-width: 0;
    width: 100%;
}
</style>
