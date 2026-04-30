<template>
    <n-data-table
        size="small"
        remote
        :columns="columns"
        :data="waiting_campaigns || []"
        :loading="isTableLoading"
        :locale="{ emptyText: tableEmptyText }"
        aria-label="Waiting campaigns table"
    />
</template>

<script setup lang="ts">
import { computed, h } from 'vue'
import { NButton } from 'naive-ui/es/button'
import { NDataTable, type DataTableColumns } from 'naive-ui/es/data-table'
import { useDialog } from 'naive-ui/es/dialog'
import { useMessage } from 'naive-ui/es/message'
import { fetchJson } from '../api/client'
import { useTradeTableFeed } from '../composables/useTradeTableFeed'
import { resolveTradeDateTime } from '../helpers/tradeTable'
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
    waitingText: 'Waiting for sidestep campaigns...',
    emptyText: 'No waiting campaigns',
    normalizeRows: (rawRows) => {
        trades_store.setWaitingCampaigns(rawRows as any[])
        return trades_store.waitingCampaigns as WaitingCampaignRow[]
    },
})

function formatReason(reason: string | null | undefined): string {
    switch (reason) {
        case 'sidestep_exit':
            return 'Sidestep exit'
        case 'take_profit':
            return 'Take profit'
        case 'trailing_take_profit':
            return 'Trailing TP'
        case 'manual_stop':
            return 'Manual stop'
        case 'manual_sell':
            return 'Manual sell'
        case 'stop_loss':
            return 'Stop loss'
        case 'autopilot_timeout':
            return 'Autopilot timeout'
        default:
            return 'Unknown'
    }
}

async function handleStopCampaign(rowData: WaitingCampaignRow): Promise<void> {
    const d = dialog.warning({
        title: 'Stop waiting campaign',
        content: `Stop the waiting sidestep campaign for ${rowData.symbol}?`,
        positiveText: 'Stop campaign',
        negativeText: 'Cancel',
        onPositiveClick: async () => {
            d.loading = true
            try {
                const result = await fetchJson<{ result: string }>(
                    `/trades/waiting/stop/${rowData.campaign_id}`,
                    { method: 'POST' },
                )
                if (result.result === 'stopped') {
                    message.success(`Stopped sidestep campaign for ${rowData.symbol}.`)
                    return
                }
                message.error(`Failed stopping sidestep campaign for ${rowData.symbol}.`)
            } catch (error) {
                const detail = error instanceof Error ? error.message : 'Unknown error'
                message.error(
                    `Failed stopping sidestep campaign for ${rowData.symbol}: ${detail}`,
                )
            }
        },
    })
}

const columns = computed<DataTableColumns<WaitingCampaignRow>>(() => [
    {
        title: 'Pair',
        key: 'symbol',
    },
    {
        title: 'Gate',
        key: 'gate_status',
        render: (rowData) => rowData.gate_detail,
    },
    {
        title: 'Sidesteps',
        key: 'sidestep_count',
    },
    {
        title: 'Last Exit',
        key: 'last_exit_reason',
        render: (rowData) => formatReason(rowData.last_exit_reason),
    },
    {
        title: 'Cooldown Until',
        key: 'cooldown_until',
        render: (rowData) => {
            if (!rowData.cooldown_until) {
                return 'Ready'
            }
            const { date, time } = resolveTradeDateTime(rowData.cooldown_until)
            return [h('div', date), h('div', time)]
        },
    },
    {
        title: 'Action',
        key: 'action',
        align: 'center',
        render: (rowData) =>
            h(
                NButton,
                {
                    size: 'small',
                    type: 'warning',
                    ghost: true,
                    onClick: () => handleStopCampaign(rowData),
                },
                { default: () => 'Stop' },
            ),
    },
])
</script>
