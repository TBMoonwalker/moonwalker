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
import { NButton } from 'naive-ui/es/button'
import { NButtonGroup } from 'naive-ui/es/button-group'
import { NDataTable, type DataTableColumns } from 'naive-ui/es/data-table'
import { NDatePicker } from 'naive-ui/es/date-picker'
import { NDivider } from 'naive-ui/es/divider'
import { useDialog } from 'naive-ui/es/dialog'
import { NIcon } from 'naive-ui/es/icon'
import { NInputNumber } from 'naive-ui/es/input-number'
import { useMessage } from 'naive-ui/es/message'
import { NSlider } from 'naive-ui/es/slider'
import { NTooltip } from 'naive-ui/es/tooltip'
import { useWebSocketDataStore } from '../stores/websocket'
import { useTradesStore } from '../stores/trades'
import { storeToRefs } from 'pinia'
import { ArrowForwardCircleOutline } from '@vicons/ionicons5'
import { fetchJson } from '../api/client'
import { formatTradingViewDateParts } from '../helpers/date'
import OpenTradeExpandedRow from './OpenTradeExpandedRow.vue'

const open_trade_store = useWebSocketDataStore("openTrades")
const open_trade_data = storeToRefs(open_trade_store)
const statistics_store = useWebSocketDataStore("statistics")
const statistics_data = storeToRefs(statistics_store)
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

function toFiniteNonNegative(value: unknown): number {
    const parsed = Number(value)
    if (!Number.isFinite(parsed) || parsed < 0) {
        return 0
    }
    return parsed
}

function formatOrderAmount(value: number): string {
    const normalized = toFiniteNonNegative(value)
    return normalized.toFixed(2)
}

function formatPrice(value: number): string {
    return toFiniteNonNegative(value).toFixed(8).replace(/\.?0+$/, '')
}

const availableFunds = computed(() => {
    const payload = statistics_data.data.value as Record<string, unknown> | null
    return toFiniteNonNegative(payload?.funds_available)
})

function clampToRange(value: number, min: number, max: number): number {
    if (!Number.isFinite(value)) {
        return min
    }
    return Math.max(min, Math.min(max, value))
}

function floorToDecimals(value: number, decimals: number): number {
    const factor = 10 ** decimals
    return Math.floor(value * factor) / factor
}

function roundToDecimals(value: number, decimals: number): number {
    const factor = 10 ** decimals
    return Math.round(value * factor) / factor
}

function snapToMarkers(
    value: number,
    markers: number[],
    tolerance: number,
): number {
    for (const marker of markers) {
        if (Math.abs(value - marker) <= tolerance) {
            return marker
        }
    }
    return value
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

function getPreviousBuyPrice(rowData: RowData): number {
    if (Array.isArray(rowData.safetyorder) && rowData.safetyorder.length > 0) {
        const sortedSafetyOrders = [...rowData.safetyorder].sort(
            (a, b) => Number(a.timestamp) - Number(b.timestamp),
        )
        const lastSafetyOrder = sortedSafetyOrders[sortedSafetyOrders.length - 1]
        return Number(lastSafetyOrder.price) || 0
    }
    return Number(rowData.baseorder?.price) || Number(rowData.avg_price) || 0
}

function calculateSoPercentage(price: number, previousPrice: number): number {
    if (!Number.isFinite(price) || !Number.isFinite(previousPrice) || previousPrice <= 0) {
        return 0
    }
    return Number((((price - previousPrice) / previousPrice) * 100).toFixed(2))
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
    const [symbol, currency] = data["symbol"].toLowerCase().split("/")
    const maxAmount = floorToDecimals(toFiniteNonNegative(availableFunds.value), 2)
    if (maxAmount <= 0) {
        message.error(`No available ${currency.toUpperCase()} funds`)
        return
    }
    const amount = ref(maxAmount)
    const marks = {
        0: '0%',
        [roundToDecimals(maxAmount * 0.25, 2)]: '25%',
        [roundToDecimals(maxAmount * 0.5, 2)]: '50%',
        [roundToDecimals(maxAmount * 0.75, 2)]: '75%',
        [maxAmount]: '100%',
    }
    const markerValues = Object.keys(marks)
        .map((key) => Number(key))
        .filter((value) => Number.isFinite(value))
    const snapTolerance = Math.max(0.02, roundToDecimals(maxAmount * 0.015, 2))
    const d = dialog.info({
        title: 'Adding funds',
        content: () => h('div', { style: 'display:flex; flex-direction:column; gap:10px; min-width:260px;' }, [
            h('div', { style: 'font-size:12px; opacity:0.75;' }, `Available ${currency.toUpperCase()}: ${formatOrderAmount(maxAmount)}`),
            h(NSlider, {
                min: 0,
                max: maxAmount,
                step: 0.01,
                marks,
                value: amount.value,
                'onUpdate:value': (value: number | [number, number]) => {
                    const resolved = Array.isArray(value) ? Number(value[0]) : Number(value)
                    const clamped = roundToDecimals(clampToRange(resolved, 0, maxAmount), 2)
                    amount.value = snapToMarkers(clamped, markerValues, snapTolerance)
                },
            }),
            h(NInputNumber, {
                min: 0,
                max: maxAmount,
                step: 0.01,
                precision: 2,
                value: amount.value,
                placeholder: `Add amount in ${currency.toUpperCase()}`,
                'onUpdate:value': (value: number | null) => {
                    amount.value = roundToDecimals(
                        clampToRange(Number(value ?? 0), 0, maxAmount),
                        2,
                    )
                },
            }),
        ]),
        positiveText: 'Add funds',
        negativeText: 'Cancel',
        onPositiveClick: async () => {
            d.loading = true
            const finalAmount = roundToDecimals(
                clampToRange(amount.value, 0, maxAmount),
                2,
            )
            if (finalAmount <= 0) {
                d.loading = false
                message.error(`Amount must be greater than 0 ${currency.toUpperCase()}`)
                return false
            }
            const orderAmount = formatOrderAmount(finalAmount)
            const result = await fetchJson<{ result: string }>(`/orders/buy/${symbol + "-" + currency}/${orderAmount}`)
            if (result["result"] == "new_so") {
                message.success('Added ' + orderAmount + ' ' + currency.toUpperCase() + ' for ' + symbol.toUpperCase())
            } else {
                message.error('Failed to add ' + orderAmount + ' ' + currency.toUpperCase() + ' for ' + symbol.toUpperCase())
            }

        },
        onNegativeClick: () => {
            message.error('Cancelled')
        }
    })
}

function handle_add_manual_buy(data: RowData) {
    const symbol = String(data.symbol || '').toUpperCase()
    const [, quoteCurrency] = symbol.split("/")
    const previousPrice = getPreviousBuyPrice(data)
    const price = ref(previousPrice > 0 ? previousPrice : Number(data.current_price) || 0)
    const quoteAmount = ref<number | null>(null)
    const timestampMs = ref<number | null>(Date.now())

    const orderSize = computed(() => {
        const localQuoteAmount = Number(quoteAmount.value ?? 0)
        if (!Number.isFinite(localQuoteAmount)) {
            return 0
        }
        return localQuoteAmount
    })
    const baseAmount = computed(() => {
        const localPrice = Number(price.value ?? 0)
        const localQuoteAmount = Number(quoteAmount.value ?? 0)
        if (
            !Number.isFinite(localPrice) ||
            localPrice <= 0 ||
            !Number.isFinite(localQuoteAmount)
        ) {
            return 0
        }
        return localQuoteAmount / localPrice
    })
    const soPercentage = computed(() =>
        calculateSoPercentage(Number(price.value ?? 0), previousPrice),
    )

    const d = dialog.info({
        title: `Add order manually for ${symbol}`,
        content: () => h('div', { style: 'display:flex; flex-direction:column; gap:10px; min-width:300px;' }, [
            h('div', { style: 'font-size:12px; opacity:0.75;' }, `Previous buy price: ${formatPrice(previousPrice)}`),
            h(NDatePicker, {
                value: timestampMs.value,
                type: 'datetime',
                clearable: false,
                'onUpdate:value': (value: number | null) => {
                    timestampMs.value = value
                },
            }),
            h(NInputNumber, {
                value: price.value,
                min: 0.00000001,
                precision: 8,
                placeholder: 'Price',
                'onUpdate:value': (value: number | null) => {
                    price.value = Number(value ?? 0)
                },
            }),
            h(NInputNumber, {
                value: quoteAmount.value,
                min: 0.00000001,
                precision: 8,
                placeholder: `Amount (${quoteCurrency})`,
                'onUpdate:value': (value: number | null) => {
                    quoteAmount.value = value
                },
            }),
            h('div', { style: 'font-size:12px; opacity:0.85;' }, `Order size: ${formatPrice(orderSize.value)} ${quoteCurrency}`),
            h('div', { style: 'font-size:12px; opacity:0.85;' }, `Asset amount (derived): ${formatPrice(baseAmount.value)}`),
            h('div', { style: 'font-size:12px; opacity:0.85;' }, `SO %: ${soPercentage.value.toFixed(2)}%`),
        ]),
        positiveText: 'Add order manually',
        negativeText: 'Cancel',
        onPositiveClick: async () => {
            d.loading = true
            const finalTimestamp = Number(timestampMs.value ?? 0)
            const finalPrice = Number(price.value ?? 0)
            const finalQuoteAmount = Number(quoteAmount.value ?? 0)
            if (!Number.isFinite(finalTimestamp) || finalTimestamp <= 0) {
                d.loading = false
                message.error('Please enter a valid date')
                return false
            }
            if (!Number.isFinite(finalPrice) || finalPrice <= 0) {
                d.loading = false
                message.error('Please enter a valid price')
                return false
            }
            if (!Number.isFinite(finalQuoteAmount) || finalQuoteAmount <= 0) {
                d.loading = false
                message.error('Please enter a valid amount')
                return false
            }
            const finalBaseAmount = finalQuoteAmount / finalPrice
            try {
                const result = await fetchJson<{ result: string; data?: { so_percentage?: number } }>('/orders/buy/manual', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        symbol,
                        date: finalTimestamp,
                        price: finalPrice,
                        amount: finalBaseAmount,
                    }),
                })
                if (result.result === 'manual_so') {
                    const effectiveSo = Number(result.data?.so_percentage ?? soPercentage.value)
                    message.success(
                        `Added manual order for ${symbol} (${formatPrice(finalQuoteAmount)} ${quoteCurrency} at ${formatPrice(finalPrice)}, SO ${effectiveSo.toFixed(2)}%)`,
                    )
                } else {
                    message.error(`Failed to add manual order for ${symbol}`)
                }
            } catch (error) {
                d.loading = false
                message.error(String(error))
                return false
            }
            return true
        },
        onNegativeClick: () => {
            message.error('Cancelled')
        },
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
                    onAddOrderManually: handle_add_manual_buy,
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
