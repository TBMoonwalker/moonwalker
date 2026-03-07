<template>
    <n-data-table
        size="small"
        remote
        ref="table"
        :columns="columns_open_trades"
        :data="open_trades || []"
        :loading="isTableLoading"
        :row-class-name="row_classes"
        :render-expand-icon="renderExpandIcon"
        :locale="{ emptyText: tableEmptyText }"
        aria-label="Open trades table"
    />
</template>

<script setup lang="ts">
import { computed, h, onMounted, onUnmounted, ref, watch } from 'vue'
import { NButton, NButtonGroup, NDataTable, NDivider, NIcon, NInput, NSlider, NTooltip, type DataTableColumns, useDialog, useMessage } from 'naive-ui'
import { useWebSocketDataStore } from '../stores/websocket'
import { useTradesStore } from '../stores/trades'
import { storeToRefs } from 'pinia'
import { ArrowForwardCircleOutline } from '@vicons/ionicons5'
import { fetchJson } from '../api/client'
import { formatTradingViewDateParts } from '../helpers/date'
import OpenTradeExpandedRow from './OpenTradeExpandedRow.vue'

const open_trade_store = useWebSocketDataStore("openTrades")
const open_trade_data = storeToRefs(open_trade_store)
const trades_store = useTradesStore()
const open_trades = ref()

const dialog = useDialog()
const message = useMessage()

const viewportWidth = ref(window.innerWidth)

const isMobile = computed(() => viewportWidth.value < 768)
const isTablet = computed(() => viewportWidth.value >= 768 && viewportWidth.value < 1200)
const isTableLoading = computed(
    () => !open_trade_data.hasReceivedData.value && open_trade_data.status.value !== 'CLOSED',
)
const tableEmptyText = computed(() => {
    if (!open_trade_data.hasReceivedData.value) {
        return 'Waiting for live open trades...'
    }
    return 'No open trades'
})

const handleResize = () => {
    viewportWidth.value = window.innerWidth
}

type TimeframeChoice = {
    timerange: string
    seconds: number
}

type ConfigResponse = {
    timeframe?: string | null
}

const TIMEFRAME_CHOICES: TimeframeChoice[] = [
    { timerange: "1m", seconds: 60 },
    { timerange: "5min", seconds: 5 * 60 },
    { timerange: "15min", seconds: 15 * 60 },
    { timerange: "30min", seconds: 30 * 60 },
    { timerange: "60min", seconds: 60 * 60 },
    { timerange: "4h", seconds: 4 * 60 * 60 },
    { timerange: "1D", seconds: 24 * 60 * 60 },
]

const configuredMinTimeframe = ref<TimeframeChoice>({ timerange: "15min", seconds: 15 * 60 })

function parseTimeframeSeconds(rawValue: string | null | undefined): number | null {
    const normalized = String(rawValue ?? "").trim().toLowerCase().replace("min", "m")
    const match = normalized.match(/^(\d+)([mhd])$/)
    if (!match) {
        return null
    }
    const value = Number(match[1])
    const unit = match[2]
    if (!Number.isFinite(value) || value <= 0) {
        return null
    }
    if (unit === "m") {
        return value * 60
    }
    if (unit === "h") {
        return value * 60 * 60
    }
    if (unit === "d") {
        return value * 24 * 60 * 60
    }
    return null
}

function resolveMinTimeframe(configured: string | null | undefined): TimeframeChoice {
    const configuredSeconds = parseTimeframeSeconds(configured)
    if (!configuredSeconds) {
        return configuredMinTimeframe.value
    }
    const matching = TIMEFRAME_CHOICES.find((choice) => choice.seconds >= configuredSeconds)
    return matching ?? TIMEFRAME_CHOICES[TIMEFRAME_CHOICES.length - 1]
}

async function loadConfiguredMinTimeframe(): Promise<void> {
    try {
        const config = await fetchJson<ConfigResponse>('/config/all')
        configuredMinTimeframe.value = resolveMinTimeframe(config.timeframe)
    } catch (_error) {
        configuredMinTimeframe.value = resolveMinTimeframe(null)
    }
}

watch(open_trade_data.data, async (newData) => {
    if (!Array.isArray(newData)) {
        open_trades.value = []
        return
    }
    const websocket_data = newData as any[]
    trades_store.setOpenTrades(websocket_data)
    open_trades.value = trades_store.openTrades
}, { immediate: true })

type RowData = {
    id: number
    symbol: string
    amount: number
    cost: number
    profit: number
    profit_percent: number
    current_price: number
    tp_price: number
    avg_price: number
    so_count: number
    open_date: string
    baseorder: OrderData
    safetyorder: Array<OrderData>
    precision: number
    unsellable_amount?: number
    unsellable_reason?: string | null
    unsellable_min_notional?: number | null
    unsellable_estimated_notional?: number | null
}

type OrderData = {
    id: number
    timestamp: string
    ordersize: number
    amount: number
    symbol: string
    price: number
}

function getSafetyOrderCount(rowData: RowData): number {
    if (Array.isArray(rowData.safetyorder)) {
        return rowData.safetyorder.length
    }
    return Number(rowData.so_count ?? 0)
}

function isUnsellableRemainder(rowData: RowData): boolean {
    return Number(rowData.unsellable_amount ?? 0) > 0 && Boolean(rowData.unsellable_reason)
}

function getUnsellableMessage(rowData: RowData): string {
    const remainingAmount = Number(rowData.unsellable_amount ?? 0)
    const [symbol] = rowData.symbol.split("/")
    const estimatedNotional = rowData.unsellable_estimated_notional
    const minNotional = rowData.unsellable_min_notional

    const parts: string[] = [
        `Unsellable remainder for ${rowData.symbol}: ${remainingAmount.toFixed(8)} ${symbol}.`,
    ]
    if (estimatedNotional !== null && estimatedNotional !== undefined) {
        parts.push(`Estimated notional: ${Number(estimatedNotional).toFixed(8)}.`)
    }
    if (minNotional !== null && minNotional !== undefined) {
        parts.push(`Minimum notional required: ${Number(minNotional).toFixed(8)}.`)
    }
    parts.push("Use Stop and close the remainder manually on the exchange.")
    return parts.join(" ")
}

function formatFixed(value: unknown, decimals = 2): string {
    const parsed = Number(value)
    if (!Number.isFinite(parsed)) {
        return (0).toFixed(decimals)
    }
    return parsed.toFixed(decimals)
}

function formatAssetAmount(value: unknown, maxDecimals = 8): string {
    const parsed = Number(value)
    if (!Number.isFinite(parsed)) {
        return "0"
    }
    return parsed.toFixed(maxDecimals).replace(/\.?0+$/, "")
}

function resolveDateTime(value: string): { date: string; time: string } {
    const parts = formatTradingViewDateParts(value)
    if (parts.time) {
        return parts
    }
    const raw = String(value).trim()
    const match = raw.match(/^(.*)\s(\d{2}:\d{2}(?::\d{2})?)$/)
    if (!match) {
        return parts
    }
    return { date: match[1], time: match[2] }
}

function handle_deal_sell(data: any) {
    const d = dialog.warning({
        title: 'Selling deal',
        content: 'Do you like to sell ' + data["amount"] + ' ' + data["symbol"] + ' ?',
        positiveText: 'Sell',
        negativeText: 'Do not sell',
        onPositiveClick: async () => {
            d.loading = true
            const [symbol, currency] = data["symbol"].toLowerCase().split("/")
            const result = await fetchJson<{ result: string }>(`/orders/sell/${symbol + "-" + currency}`)
            if (result["result"] == "sell") {
                message.success('Sold ' + data["amount"] + ' ' + data["symbol"])
            } else {
                message.error('Failed to sell' + data["amount"] + ' ' + data["symbol"] + ' - please check your logs')
            }

        },
        onNegativeClick: () => {
            message.error('Cancelled')
        }
    })
}

function handle_deal_buy(data: any) {
    var amount = ""
    const [symbol, currency] = data["symbol"].toLowerCase().split("/")
    const d = dialog.info({
        title: 'Adding funds',
        content: () => h(NInput, { onUpdateValue: (value) => { amount = value }, allowInput: (value: string) => !value || /^\d+$/.test(value), placeholder: "Add amount in " + currency.toUpperCase() }),
        positiveText: 'Add funds',
        negativeText: 'Cancel',
        onPositiveClick: async () => {
            d.loading = true
            const result = await fetchJson<{ result: string }>(`/orders/buy/${symbol + "-" + currency}/${amount}`)
            if (result["result"] == "new_so") {
                message.success('Added ' + amount + ' ' + currency.toUpperCase() + ' for ' + symbol.toUpperCase())
            } else {
                message.error('Failed to add ' + amount + ' ' + currency.toUpperCase() + ' for ' + symbol.toUpperCase())
            }

        },
        onNegativeClick: () => {
            message.error('Cancelled')
        }
    })
}

function handle_deal_stop(data: any) {
    const d = dialog.warning({
        title: 'Stopping deal',
        content: 'Do you like to stop the deal for ' + data["symbol"] + ' ?',
        positiveText: 'Stop',
        negativeText: 'Do not stop',
        onPositiveClick: async () => {
            d.loading = true
            const [symbol, currency] = data["symbol"].toLowerCase().split("/")
            const result = await fetchJson<{ result: string }>(`/orders/stop/${symbol + "-" + currency}`)
            if (result["result"] == "stop") {
                message.success('Stopped ' + data["symbol"] + ' Please trade it manually on your exchange')
            } else {
                message.error('Failed to stop' + data["symbol"] + ' - please check your logs')
            }

        },
        onNegativeClick: () => {
            message.error('Cancelled')
        }
    })
}

function row_classes(row: RowData) {
    if (Math.sign(row.profit_percent) >= 0) {
        return 'green'
    } else {
        return 'red'
    }
}

const renderExpandIcon = () => {
    return h(NIcon, { size: 24, color: "#63e2b7" }, { default: () => h(ArrowForwardCircleOutline) })
}


const columns_trades = (): DataTableColumns<RowData> => {
    const columns: DataTableColumns<RowData> = [
        {
            type: 'expand',
            expandable: (rowData) => rowData.symbol != "",
            renderExpand: (rowData) =>
                h(OpenTradeExpandedRow, {
                    rowData,
                    minTimeframe: configuredMinTimeframe.value,
                }),
        },
        {
            title: 'Symbol',
            key: 'symbol',
            render: (rowData, index) => {
                const [symbol, currency] = rowData.symbol.split("/")
                return [
                    h('div', `#${index + 1}`),

                    h(NDivider, { dashed: true }),
                    h('div', symbol),
                ]
            }
        },
        {
            title: 'Cost',
            key: 'amount',
            render: (rowData) => {
                const [symbol, currency] = rowData.symbol.split("/")
                const amount = `${formatAssetAmount(rowData.amount)} ${symbol}`
                const cost = `${formatFixed(rowData.cost)} ${currency}`
                return [
                    h('div', amount),

                    h(NDivider, { dashed: true }),
                    h('div', cost),
                ]
            }
        },
        {
            title: 'PNL',
            key: 'profit',
            render: (rowData) => {
                const [symbol, currency] = rowData.symbol.split("/")
                const profit_percent = `${formatFixed(rowData.profit_percent)} %`
                const pnl = `${formatFixed(rowData.profit)} ${currency}`
                return [
                    h('div', { class: 'profit' }, profit_percent),
                    h(NDivider, { dashed: true }),
                    h('div', pnl),
                ]
            }
        },
        {
            title: 'TP/SO',
            key: 'tp_price',
            render: (rowData) => {
                const avg_price = rowData.avg_price
                const tp_price = rowData.tp_price
                const current_price = rowData.current_price
                const min_price = (avg_price - (avg_price / 100) * 0.7)
                const max_price = (tp_price / 100) * 0.7 + Number(tp_price)
                const marks = { [avg_price]: 'avg', [tp_price]: 'tp' }
                const fillColor = current_price < avg_price
                    ? 'rgb(224, 108, 117)'
                    : 'rgb(99, 226, 183)'
                return [
                    h(NSlider, { value: [current_price, avg_price], range: true, min: min_price, max: max_price, disabled: true, themeOverrides: { fillColor, handleSize: '8px', opacityDisabled: '1' } }),
                    h(NDivider, { dashed: true }),
                    h('div', String(getSafetyOrderCount(rowData))),
                ]
            },
            align: 'center'
        },
        {
            title: 'Action',
            key: 'action',
            render: (rowData) => {
                if (isUnsellableRemainder(rowData)) {
                    return [
                        h(NTooltip, {}, {
                            trigger: () =>
                                h(NButton, {
                                    type: 'error',
                                    size: 'small',
                                    ghost: true,
                                    onClick: () => handle_deal_stop(rowData),
                                }, { default: () => 'Stop (Unsellable)' }),
                            default: () => getUnsellableMessage(rowData),
                        })
                    ]
                }
                return [
                    h(NButtonGroup, { size: 'small', vertical: true }, {
                        default: () => [
                            h(NButton, { primary: true, size: 'small', ghost: true, color: "#63e2b7", onClick: () => handle_deal_sell(rowData) }, { default: () => 'Sell' }),
                            h(NButton, { primary: true, size: 'small', ghost: true, color: "#63e2b7", onClick: () => handle_deal_buy(rowData) }, { default: () => 'Buy' }),
                            h(NButton, { primary: true, size: 'small', ghost: true, color: "#63e2b7", onClick: () => handle_deal_stop(rowData) }, { default: () => 'Stop' })
                        ]
                    })
                ]
            },
            align: 'center'
        },
        {
            title: 'Opened',
            key: 'open_date',
            align: 'center',
            render: (rowData) => {
                const { date, time } = resolveDateTime(rowData.open_date)
                return [
                    h('div', date),
                    h(NDivider, { dashed: true }),
                    h('div', time),
                ]
            },
        },
    ]

    if (isMobile.value) {
        return columns.filter((column) => {
            if (!("key" in column)) {
                return true
            }
            return ["symbol", "profit", "action"].includes(String(column.key))
        })
    }

    if (isTablet.value) {
        return columns.filter((column) => {
            if (!("key" in column)) {
                return true
            }
            return ["symbol", "amount", "profit", "action", "open_date"].includes(
                String(column.key),
            )
        })
    }

    return columns
}

const columns_open_trades = computed(() => columns_trades())

onMounted(async () => {
    window.addEventListener('resize', handleResize)
    await loadConfiguredMinTimeframe()
})

onUnmounted(() => {
    window.removeEventListener('resize', handleResize)
})

</script>

<style scoped>
:deep(.red .profit) {
    color: rgb(224, 108, 117) !important;
}

:deep(.green .profit) {
    color: rgb(99, 226, 183) !important;
}

:deep(.n-data-table-expand-trigger) {
    height: 16px;
}
</style>
