<template>
    <n-data-table size="small" remote ref="table" :columns="columns_open_trades" :data="open_trades"
        :row-class-name="row_classes" :render-expand-icon="renderExpandIcon" />
</template>

<script setup lang="ts">
import { computed, h, onMounted, onUnmounted, ref, watch } from 'vue'
import { NButton, NButtonGroup, NCard, NDataTable, NDivider, NFlex, NHighlight, NIcon, NInput, NSlider, NTimeline, NTimelineItem, NTooltip, type DataTableColumns, useDialog, useMessage } from 'naive-ui'
import { useWebSocketDataStore } from '../stores/websocket'
import { useTradesStore } from '../stores/trades'
import { storeToRefs } from 'pinia'
import { createDecimal } from '../helpers/validators'
import { createChart, CandlestickSeries, createSeriesMarkers } from 'lightweight-charts'
import { ArrowForwardCircleOutline } from '@vicons/ionicons5'
import { fetchJson } from '../api/client'
import { useOhlcvStore } from '../stores/ohlcv'

const open_trade_store = useWebSocketDataStore("openTrades")
const open_trade_data = storeToRefs(open_trade_store)
const trades_store = useTradesStore()
const open_trades = ref()
const ohlcvStore = useOhlcvStore()

const dialog = useDialog()
const message = useMessage()

const MAX_VISIBLE_CANDLES = 500
const PRE_ROLL_CANDLES = 2
const viewportWidth = ref(window.innerWidth)

const isMobile = computed(() => viewportWidth.value < 768)
const isTablet = computed(() => viewportWidth.value >= 768 && viewportWidth.value < 1200)

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

function selectTimeframe(
    beginTimestamp: string | number,
    minTimeframe: TimeframeChoice,
): TimeframeChoice {
    const beginMs = Number(beginTimestamp)
    const nowMs = Date.now()
    const durationSeconds = Math.max(0, Math.floor((nowMs - beginMs) / 1000))
    const choices = TIMEFRAME_CHOICES.filter(
        (choice) => choice.seconds >= minTimeframe.seconds,
    )

    for (const choice of choices) {
        if (durationSeconds / choice.seconds <= MAX_VISIBLE_CANDLES) {
            return choice
        }
    }

    return choices[choices.length - 1]
}

function getLocalOffsetSeconds(): number {
    return -new Date().getTimezoneOffset() * 60
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
    if (newData !== undefined && newData !== null) {
        const websocket_data = newData as any[]
        trades_store.setOpenTrades(websocket_data)
        open_trades.value = trades_store.openTrades
    }
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
            renderExpand: (rowData) => {
                const [symbol, currency] = rowData.symbol.split("/")
                const chartRef = ref()
                let chart: any
                return [
                    h(NFlex, { justify: 'space-around' }, {
                        default: () => [
                            h(NCard, {}, {
                                default: () =>
                                    h(NTimeline, {
                                        horizontal: false
                                    }, () => {
                                        let timeline_items: Array<any> = []
                                        // Baseorder
                                        let timestamp = new Date(Math.trunc(parseFloat(rowData.baseorder.timestamp)))
                                        let date = timestamp.toLocaleString()
                                        timeline_items[0] = h(NTimelineItem, {
                                            title: "Baseorder",
                                            content: "Order size: " + rowData.baseorder.ordersize + " | Amount: " + rowData.baseorder.amount + " | Price: " + rowData.baseorder.price,
                                            type: 'info',
                                            time: date,
                                        })

                                        // Safety Orders
                                        if (rowData.safetyorder) {
                                            rowData.safetyorder.forEach(function (val: any, i: any) {
                                                let timestamp = new Date(Math.trunc(parseFloat(val.timestamp)))
                                                let date = timestamp.toLocaleString()
                                                timeline_items[(i + 1)] = h(NTimelineItem, {
                                                    title: "Safetyorder " + (i + 1),
                                                    content: "Order size: " + val.ordersize + " | Amount: " + val.amount + " | Price: " + val.price + " | Percentage: " + val.so_percentage,
                                                    type: 'success',
                                                    time: date,
                                                })
                                            })
                                        }
                                        return timeline_items
                                    })
                            }),
                            h(NCard, {}, {
                                default: () =>
                                    h('div', {
                                        ref: chartRef, style: "height: 400px",
                                        onVnodeMounted: async () => {
                                            let end_timestamp = null
                                            const begin_timestamp = rowData.baseorder.timestamp
                                            if (rowData.safetyorder) {
                                                end_timestamp = rowData.safetyorder[rowData.safetyorder.length - 1].timestamp
                                            }
                                            //console.log("Begin timestamp: " + begin_timestamp + ", End timestamp: " + end_timestamp)

                                            // Create precision for candlestick prices
                                            const precision = createDecimal(rowData.precision)
                                            const timeframe = selectTimeframe(begin_timestamp, configuredMinTimeframe.value)
                                            const history_start = Math.max(
                                                0,
                                                Number(begin_timestamp) -
                                                timeframe.seconds * PRE_ROLL_CANDLES * 1000,
                                            )

                                            chart = createChart(chartRef.value, {
                                                autoSize: true,
                                                layout: {
                                                    background: { color: 'rgb(24, 24, 28)' },
                                                    textColor: '#fff',
                                                },
                                                grid: {
                                                    vertLines: { visible: false },
                                                    horzLines: { visible: false },
                                                },
                                                timeScale: {
                                                    borderVisible: false,
                                                    timeVisible: true,
                                                },
                                                rightPriceScale: {
                                                    borderVisible: false
                                                },
                                                handleScroll: true,
                                                handleScale: false,
                                            })
                                            const candlestickSeries = chart.addSeries(CandlestickSeries, {
                                                upColor: "rgb(99, 226, 183)",
                                                borderUpColor: "rgb(99, 226, 183)",
                                                wickUpColor: "rgb(99, 226, 183)",
                                                downColor: "rgb(224, 108, 117)",
                                                borderDownColor: "rgb(224, 108, 117)",
                                                wickDownColor: "rgb(224, 108, 117)",
                                                priceFormat: {
                                                    type: 'price',
                                                    minMove: precision,
                                                },
                                            })

                                            // OHLCV data from Moonwalker
                                            const cacheKey = `${symbol}-${currency}-${timeframe.timerange}-${history_start}`
                                            let ticker_data = null
                                            try {
                                                // Always refresh chart data when opening the panel.
                                                ticker_data = await fetchJson(`/data/ohlcv/${symbol + "-" + currency.toUpperCase()}/${timeframe.timerange}/${history_start}/0`)
                                                ohlcvStore.set(cacheKey, ticker_data)
                                            } catch (_error) {
                                                ticker_data = ohlcvStore.get(cacheKey) ?? []
                                            }
                                            const localOffsetSeconds = getLocalOffsetSeconds()
                                            const localTickerData = (ticker_data as Array<Record<string, number>>).map(
                                                (entry) => ({
                                                    ...entry,
                                                    time: Number(entry.time) + localOffsetSeconds,
                                                }),
                                            )
                                            candlestickSeries.setData(localTickerData)

                                            let marker_data = []

                                            // Take profit price line
                                            candlestickSeries.createPriceLine({
                                                price: Number(rowData.tp_price),
                                                color: 'orange',
                                                lineWidth: 2,
                                                lineStyle: 0,
                                                axisLabelVisible: true,
                                                title: 'TP'
                                            })

                                            // Correct marker timestamp shift
                                            const seconds = timeframe.seconds

                                            let baseorder_datetime = Math.trunc(Number(begin_timestamp) / 1000) - (Math.trunc(Number(begin_timestamp) / 1000) % seconds)
                                            baseorder_datetime += localOffsetSeconds
                                            // Baseorder marker
                                            //const baseorderMarker = createSeriesMarkers(candles)
                                            marker_data.push({
                                                time: baseorder_datetime,
                                                position: 'belowBar',
                                                color: '#f68410',
                                                shape: 'arrowUp',
                                                text: 'Buy',
                                            })

                                            // Baseorder price line
                                            candlestickSeries.createPriceLine({
                                                price: rowData.baseorder.price,
                                                color: 'green',
                                                lineWidth: 2,
                                                lineStyle: 2,
                                                axisLabelVisible: true,
                                                title: 'BO',
                                            })

                                            if (rowData.safetyorder) {
                                                rowData.safetyorder.forEach(function (val: any, i: any) {
                                                    let safetyorder_datetime = Math.trunc(Number(val.timestamp) / 1000) - (Math.trunc(Number(val.timestamp) / 1000) % seconds)
                                                    safetyorder_datetime += localOffsetSeconds
                                                    // Safetyorder marker
                                                    marker_data.push({
                                                        time: safetyorder_datetime,
                                                        position: 'belowBar',
                                                        color: '#f68410',
                                                        shape: 'arrowUp',
                                                        text: 'Buy',
                                                    })

                                                    // Safetyorder price line
                                                    candlestickSeries.createPriceLine({
                                                        price: val.price,
                                                        color: 'green',
                                                        lineWidth: 2,
                                                        lineStyle: 2,
                                                        axisLabelVisible: true,
                                                        title: 'SO' + (i + 1),
                                                    })

                                                })
                                            }

                                            createSeriesMarkers(candlestickSeries, marker_data)

                                            chart.timeScale().fitContent()
                                        },
                                        onVnodeUnmounted: () => {
                                            if (chart) {
                                                chart.remove();
                                                chart = null;
                                            }
                                        },
                                    })
                            })
                        ]

                    })]
            }
        },
        {
            title: 'Symbol',
            key: 'symbol',
            render: (rowData, index) => {
                const [symbol, currency] = rowData.symbol.split("/")
                return [
                    h('div', { innerHTML: "#" + (index + 1) }),

                    h(NDivider, { dashed: true }),
                    h('div', { innerHTML: symbol }),
                ]
            }
        },
        {
            title: 'Cost',
            key: 'amount',
            render: (rowData) => {
                const [symbol, currency] = rowData.symbol.split("/")
                const amount = rowData.amount + " " + symbol
                const cost = rowData.cost + " " + currency
                return [
                    h('div', { innerHTML: amount }),

                    h(NDivider, { dashed: true }),
                    h('div', { innerHTML: cost }),
                ]
            }
        },
        {
            title: 'PNL',
            key: 'profit',
            render: (rowData) => {
                const [symbol, currency] = rowData.symbol.split("/")
                const profit_percent = rowData.profit_percent.toFixed(2) + " %"
                const pnl = rowData.profit + " " + currency
                return [
                    h('div', { className: 'profit', innerHTML: profit_percent }),
                    h(NDivider, { dashed: true }),
                    h('div', { innerHTML: pnl }),
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
                const fillColor = ref()
                if (current_price < avg_price) {
                    fillColor.value = 'rgb(224, 108, 117)'
                } else {
                    fillColor.value = 'rgb(99, 226, 183)'
                }
                return [
                    h(NSlider, { value: [current_price, avg_price], range: true, min: min_price, max: max_price, disabled: true, themeOverrides: { fillColor: fillColor.value, handleSize: '8px', opacityDisabled: '1' } }),
                    h(NDivider, { dashed: true }),
                    h('div', { innerHTML: String(getSafetyOrderCount(rowData)) }),
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
                const [date, time] = rowData.open_date.split(",")
                return [
                    h('div', { innerHTML: date }),
                    h(NDivider, { dashed: true }),
                    h('div', { innerHTML: time }),
                ]
            }
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
