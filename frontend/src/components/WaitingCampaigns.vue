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

async function handleActivateCampaign(rowData: WaitingCampaignRow): Promise<void> {
    const campaignId = String(rowData.campaign_id ?? '')
    if (!campaignId) {
        message.error(`Missing sidestep campaign id for ${rowData.symbol}.`)
        return
    }

    const d = dialog.warning({
        title: 'Switch to active',
        content: `Buy back into the waiting sidestep trade for ${rowData.symbol} now?`,
        positiveText: 'Switch to active',
        negativeText: 'Cancel',
        onPositiveClick: async () => {
            d.loading = true
            try {
                const result = await fetchJson<{ result: string }>(
                    `/trades/waiting/activate/${rowData.campaign_id}`,
                    { method: 'POST' },
                )
                if (result.result === 'activated') {
                    message.success(
                        `Switched sidestep trade for ${rowData.symbol} back to active.`,
                    )
                    return
                }
                message.error(`Failed activating sidestep trade for ${rowData.symbol}.`)
            } catch (error) {
                const detail = error instanceof Error ? error.message : 'Unknown error'
                message.error(
                    `Failed activating sidestep trade for ${rowData.symbol}: ${detail}`,
                )
            }
        },
    })
}

function rowClasses(rowData: WaitingCampaignRow): string {
    if (Math.sign(Number(rowData.display_profit_percent ?? 0)) >= 0) {
        return 'green'
    }
    return 'red'
}

function formatCloseReason(reason: string | null | undefined): string {
    switch (String(reason ?? '').trim().toLowerCase()) {
        case 'sidestep_exit':
            return 'Sidestep exit'
        case 'manual_stop':
            return 'Manual stop'
        case 'take_profit':
            return 'Take profit'
        case 'trailing_take_profit':
            return 'Trailing take profit'
        case 'stop_loss':
            return 'Stop loss'
        case 'manual_sell':
            return 'Manual sell'
        default:
            return 'Unknown'
    }
}

function resolveReentryStatusType(
    rowData: WaitingCampaignRow,
): 'default' | 'info' | 'success' | 'warning' {
    switch (rowData.reentry_status) {
        case 'Cooldown active':
            return 'warning'
        case 'Fresh long signal recorded':
            return 'success'
        case 'Retrying after re-entry error':
            return 'info'
        default:
            return 'default'
    }
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
        key: 'display_profit',
        render: (rowData) => {
            const [, currency] = rowData.symbol.split('/')
            const profitPercent = `${formatFixed(Number(rowData.display_profit_percent ?? 0))} %`
            const pnl = `${formatFixed(Number(rowData.display_profit ?? 0))} ${currency}`
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
        title: 'Status',
        key: 'reentry_status',
        render: (rowData) => {
            const status = rowData.reentry_status ?? 'Watching for re-entry signal'
            const statusRows = [
                h(
                    NTag,
                    {
                        size: 'small',
                        bordered: false,
                        type: resolveReentryStatusType(rowData),
                    },
                    {
                        default: () => status,
                    },
                ),
                h(NDivider, { dashed: true }),
                h('div', `Last exit: ${formatCloseReason(rowData.last_exit_reason)}`),
            ]

            if (
                status === 'Cooldown active' &&
                rowData.cooldown_until
            ) {
                const cooldown = resolveTradeDateTime(rowData.cooldown_until)
                statusRows.push(h(NDivider, { dashed: true }))
                statusRows.push(
                    h('div', `Cooldown until ${cooldown.date} ${cooldown.time}`),
                )
            } else if (rowData.last_long_signal_at) {
                const lastSignal = resolveTradeDateTime(rowData.last_long_signal_at)
                statusRows.push(h(NDivider, { dashed: true }))
                statusRows.push(
                    h('div', `Last long signal ${lastSignal.date} ${lastSignal.time}`),
                )
            }

            return statusRows
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
                            type: 'success',
                            ghost: true,
                            onClick: () => handleActivateCampaign(rowData),
                        },
                        { default: () => 'Switch to active' },
                    ),
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
