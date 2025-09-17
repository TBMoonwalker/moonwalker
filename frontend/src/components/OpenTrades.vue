<template>
    <n-data-table size="small" remote ref="table" :columns="columns_open_trades" :data="open_trades"
        :row-class-name="row_classes" :render-expand-icon="renderExpandIcon" />
</template>

<script setup lang="ts">
import { MOONWALKER_API_PORT, MOONWALKER_API_HOST } from '../config'
import { h, ref, watch } from 'vue'
import { type DataTableColumns, NTimeline, NTimelineItem, NDivider, NSlider, NButton, NButtonGroup, useDialog, useMessage, NInput, NFlex, NCard, NIcon, NHighlight } from 'naive-ui'
import { useWebSocketDataStore } from '../stores/websocket'
import { storeToRefs } from 'pinia'
import { isFloat, createDecimal } from '../helpers/validators'
import { timezoneOffset } from '../helpers/timezone'
import { createChart, CandlestickSeries, createSeriesMarkers } from 'lightweight-charts'
import { ArrowForwardCircleOutline } from '@vicons/ionicons5'

const open_trade_store = useWebSocketDataStore("openTrades")
const open_trade_data = storeToRefs(open_trade_store)
const open_trades = ref()

const dialog = useDialog()
const message = useMessage()

watch(open_trade_data.json, async (newData) => {
    if (newData !== undefined) {
        const websocket_data = JSON.parse(newData)
        open_trades.value = websocket_data

        websocket_data.forEach(function (val: any, i: any) {
            var amount_length = 0
            var cost_length = 0
            var tp_length = 0
            var avg_length = 0
            var current_length = 0
            if (isFloat(val.amount)) {
                amount_length = open_trades.value[i].amount.toString().split('.')[1].length
            }

            if (isFloat(val.cost)) {
                cost_length = open_trades.value[i].cost.toString().split('.')[1].length
            }

            if (isFloat(val.tp_price)) {
                tp_length = open_trades.value[i].tp_price.toString().split('.')[1].length
            }

            if (isFloat(val.avg_price)) {
                avg_length = open_trades.value[i].avg_price.toString().split('.')[1].length
            }

            if (isFloat(val.current_price)) {
                current_length = open_trades.value[i].current_price.toString().split('.')[1].length
            }

            open_trades.value[i].cost = val.cost.toFixed(cost_length)
            open_trades.value[i].profit = val.profit.toFixed(2)
            open_trades.value[i].amount = val.amount.toFixed(amount_length)
            open_trades.value[i].current_price = val.current_price.toFixed(current_length)
            open_trades.value[i].tp_price = val.tp_price.toFixed(tp_length)
            open_trades.value[i].avg_price = val.avg_price.toFixed(avg_length)
            open_trades.value[i].key = val.id
            let date = new Date(Math.trunc(parseFloat(val.open_date)));
            open_trades.value[i].open_date = date.toLocaleString()
            open_trades.value[i].safetyorder = val.safetyorders
            open_trades.value[i].precision = current_length

        })
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
}

type OrderData = {
    id: number
    timestamp: string
    ordersize: number
    amount: number
    symbol: string
    price: number
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
            const result = await fetch(`http://${MOONWALKER_API_HOST}:${MOONWALKER_API_PORT}/orders/sell/${symbol + "-" + currency}`).then((response) =>
                response.json()
            )
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
            const result = await fetch(`http://${MOONWALKER_API_HOST}:${MOONWALKER_API_PORT}/orders/buy/${symbol + "-" + currency}/${amount}`).then((response) =>
                response.json()
            )
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
            const result = await fetch(`http://${MOONWALKER_API_HOST}:${MOONWALKER_API_PORT}/orders/stop/${symbol + "-" + currency}`).then((response) =>
                response.json()
            )
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
    return [
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
                                        horizontal: true
                                    }, () => {
                                        let timeline_items: Array<any> = []
                                        // Baseorder
                                        let timestamp = new Date(Math.trunc(parseFloat(rowData.baseorder.timestamp)))
                                        //console.log(timestamp)
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
                                            const ticker_data = await fetch(`http://${MOONWALKER_API_HOST}:${MOONWALKER_API_PORT}/data/ohlcv/${symbol + currency.toUpperCase()}/15min/${begin_timestamp}/${timezoneOffset()}`).then((response) =>
                                                response.json()
                                            )
                                            candlestickSeries.setData(ticker_data)

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
                                            let intervals = {
                                                '15_minutes': (3600 / 2)
                                            }
                                            let seconds = intervals['15_minutes']

                                            let baseorder_datetime = Math.trunc(Number(begin_timestamp) / 1000) - (Math.trunc(Number(begin_timestamp) / 1000) % seconds)
                                            baseorder_datetime += 60 * timezoneOffset()
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
                                                    safetyorder_datetime += 60 * timezoneOffset()
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
                    h('div', { innerHTML: rowData.so_count }),
                ]
            },
            align: 'center'
        },
        {
            title: 'Action',
            key: 'action',
            render: (rowData) => {
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
}

const columns_open_trades = columns_trades()

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
