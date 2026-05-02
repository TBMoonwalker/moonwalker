<template>
    <n-data-table
        size="small"
        remote
        :columns="columns"
        :data="waiting_campaigns || []"
        :loading="isTableLoading"
        :row-class-name="rowClasses"
        :locale="{ emptyText: tableEmptyText }"
        aria-label="Waiting sidestep trades table"
    />
</template>

<script setup lang="ts">
import { computed, h } from 'vue'
import { NButton } from 'naive-ui/es/button'
import { NButtonGroup } from 'naive-ui/es/button-group'
import { NDataTable, type DataTableColumns } from 'naive-ui/es/data-table'
import { NDivider } from 'naive-ui/es/divider'
import { useDialog } from 'naive-ui/es/dialog'
import { useMessage } from 'naive-ui/es/message'
import { NSlider } from 'naive-ui/es/slider'
import { NTag } from 'naive-ui/es/tag'
import { fetchJson } from '../api/client'
import { useTradeTableFeed } from '../composables/useTradeTableFeed'
import {
    formatAssetAmount,
    formatFixed,
    resolveTradeDateTime,
} from '../helpers/tradeTable'
import {
    useTradesStore,
    type WaitingCampaignRow,
} from '../stores/trades'

const trades_store = useTradesStore()
const dialog = useDialog()
const message = useMessage()

const {
    rows: waiting_campaigns,
    isTableLoading,
    tableEmptyText,
} = useTradeTableFeed<WaitingCampaignRow>({
    websocketId: 'waitingCampaigns',
    waitingText: 'Waiting for active sidestep trades...',
    emptyText: 'No active trades are currently waiting for sidestep re-entry',
    normalizeRows: (rawRows) => {
        trades_store.setWaitingCampaigns(rawRows as any[])
        return trades_store.waitingCampaigns as WaitingCampaignRow[]
    },
})

async function handleStopCampaign(rowData: WaitingCampaignRow): Promise<void> {
    const campaignId = String(rowData.campaign_id ?? '')
    if (!campaignId) {
        message.error(`Missing sidestep campaign id for ${rowData.symbol}.`)
        return
    }

    const d = dialog.warning({
        title: 'Stop waiting trade',
        content: `Stop the waiting sidestep trade for ${rowData.symbol}?`,
        positiveText: 'Stop trade',
        negativeText: 'Cancel',
        onPositiveClick: async () => {
            d.loading = true
            try {
                const result = await fetchJson<{ result: string }>(
                    `/trades/waiting/stop/${rowData.campaign_id}`,
                    { method: 'POST' },
                )
                if (result.result === 'stopped') {
                    message.success(`Stopped sidestep trade for ${rowData.symbol}.`)
                    return
                }
                message.error(`Failed stopping sidestep trade for ${rowData.symbol}.`)
            } catch (error) {
                const detail = error instanceof Error ? error.message : 'Unknown error'
                message.error(
                    `Failed stopping sidestep trade for ${rowData.symbol}: ${detail}`,
                )
            }
        },
    })
}

function rowClasses(rowData: WaitingCampaignRow): string {
    if (Math.sign(Number(rowData.virtual_waiting_profit_percent ?? 0)) >= 0) {
        return 'green'
    }
    return 'red'
}

const columns = computed<DataTableColumns<WaitingCampaignRow>>(() => [
    {
        title: 'Symbol',
        key: 'symbol',
        render: (rowData, index) => {
            const [token] = rowData.symbol.split('/')
            const rows = [
                h('div', `#${index + 1}`),
                h(NDivider, { dashed: true }),
                h('div', token),
                h(NDivider, { dashed: true }),
                h('div', 'Flat / waiting'),
            ]
            if (Number(rowData.sidestep_count ?? 0) > 0) {
                rows.push(h(NDivider, { dashed: true }))
                rows.push(
                    h(
                        NTag,
                        {
                            size: 'small',
                            bordered: false,
                            type: 'warning',
                        },
                        {
                            default: () =>
                                `Sidestep x${Number(rowData.sidestep_count ?? 0)}`,
                        },
                    ),
                )
            }
            return rows
        },
    },
    {
        title: 'Cost',
        key: 'waiting_reference_quote',
        render: (rowData) => {
            const [token, currency] = rowData.symbol.split('/')
            const amount = `${formatAssetAmount(Number(rowData.waiting_reference_amount ?? 0))} ${token}`
            const reserve = `${formatFixed(Number(rowData.reserved_reentry_quote ?? 0))} ${currency}`
            return [
                h('div', amount),
                h(NDivider, { dashed: true }),
                h('div', reserve),
            ]
        },
    },
    {
        title: 'PNL',
        key: 'virtual_waiting_profit',
        render: (rowData) => {
            const [, currency] = rowData.symbol.split('/')
            const profitPercent = `${formatFixed(Number(rowData.virtual_waiting_profit_percent ?? 0))} %`
            const pnl = `${formatFixed(Number(rowData.virtual_waiting_profit ?? 0))} ${currency}`
            return [
                h('div', { class: 'profit' }, profitPercent),
                h(NDivider, { dashed: true }),
                h('div', pnl),
            ]
        },
    },
    {
        title: 'Re-entry',
        key: 'waiting_reference_price',
        render: (rowData) => {
            const referencePrice = Number(rowData.waiting_reference_price ?? 0)
            const currentPrice = Number(rowData.current_price ?? 0)
            const sliderMin = Math.max(
                0,
                Math.min(referencePrice, currentPrice) * 0.993,
            )
            const sliderMax = Math.max(
                referencePrice,
                currentPrice,
                1,
            ) * 1.007
            return [
                h(NSlider, {
                    value: [currentPrice, referencePrice],
                    range: true,
                    min: sliderMin,
                    max: sliderMax,
                    disabled: true,
                    themeOverrides: {
                        fillColor:
                            currentPrice <= referencePrice
                                ? 'rgb(99, 226, 183)'
                                : 'rgb(224, 108, 117)',
                        handleSize: '8px',
                        opacityDisabled: '1',
                    },
                }),
                h(NDivider, { dashed: true }),
                h(
                    'div',
                    `Now ${formatFixed(currentPrice)} / Exit ${formatFixed(referencePrice)}`,
                ),
            ]
        },
        align: 'center',
    },
    {
        title: 'Action',
        key: 'action',
        align: 'center',
        render: (rowData) =>
            h(NButtonGroup, { size: 'medium', vertical: true }, {
                default: () => [
                    h(
                        NButton,
                        {
                            type: 'warning',
                            ghost: true,
                            onClick: () => handleStopCampaign(rowData),
                        },
                        { default: () => 'Stop' },
                    ),
                ],
            }),
    },
    {
        title: 'Opened',
        key: 'open_date',
        align: 'center',
        render: (rowData) => {
            const opened = resolveTradeDateTime(
                rowData.campaign_started_at || rowData.open_date,
            )
            const waitingSince = resolveTradeDateTime(
                rowData.last_transition_at || rowData.open_date,
            )
            return [
                h('div', opened.date),
                h(NDivider, { dashed: true }),
                h('div', waitingSince.time),
            ]
        },
    },
])
</script>

<style scoped>
:deep(.red .profit) {
    color: rgb(224, 108, 117) !important;
}

:deep(.green .profit) {
    color: rgb(99, 226, 183) !important;
}
</style>
