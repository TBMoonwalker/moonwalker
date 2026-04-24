import { computed, h, type Ref } from 'vue'
import { NButton } from 'naive-ui/es/button'
import { NButtonGroup } from 'naive-ui/es/button-group'
import { NDivider } from 'naive-ui/es/divider'
import { NIcon } from 'naive-ui/es/icon'
import { NSlider } from 'naive-ui/es/slider'
import { NTooltip } from 'naive-ui/es/tooltip'
import { type DataTableColumns } from 'naive-ui/es/data-table'
import { ArrowForwardCircleOutline } from '@vicons/ionicons5'

import OpenTradeExpandedRow from '../components/OpenTradeExpandedRow.vue'
import {
    formatAssetAmount,
    formatFixed,
    resolveTradeDateTime,
} from '../helpers/tradeTable'
import {
    getSafetyOrderCount,
    getUnsellableMessage,
    isUnsellableRemainder,
    splitTradeSymbol,
    type OpenTradeRow,
    type TimeframeChoice,
} from '../helpers/openTrades'

interface UseOpenTradeColumnsOptions {
    configuredMinTimeframe: Ref<TimeframeChoice>
    isMobile: Ref<boolean>
    isTablet: Ref<boolean>
    onAddManualBuy: (rowData: OpenTradeRow) => void
    onDealBuy: (rowData: OpenTradeRow) => void
    onDealSell: (rowData: OpenTradeRow) => void
    onDealStop: (rowData: OpenTradeRow) => void
}

const tradeActionButtonStyle = {
    minHeight: '44px',
    minWidth: '56px',
    padding: '0 12px',
}

export function useOpenTradeColumns(options: UseOpenTradeColumnsOptions) {
    function rowClasses(row: OpenTradeRow): string {
        if (Math.sign(row.profit_percent) >= 0) {
            return 'green'
        }
        return 'red'
    }

    function renderExpandIcon() {
        return h(
            NIcon,
            { size: 24, color: '#63e2b7' },
            { default: () => h(ArrowForwardCircleOutline) },
        )
    }

    function columnsTrades(): DataTableColumns<OpenTradeRow> {
        const columns: DataTableColumns<OpenTradeRow> = [
            {
                type: 'expand',
                expandable: (rowData) => rowData.symbol != '',
                renderExpand: (rowData) =>
                    h(OpenTradeExpandedRow, {
                        rowData,
                        minTimeframe: options.configuredMinTimeframe.value,
                        onAddOrderManually: options.onAddManualBuy,
                    }),
            },
            {
                title: 'Symbol',
                key: 'symbol',
                render: (rowData, index) => {
                    const [symbol] = splitTradeSymbol(rowData.symbol)
                    return [
                        h('div', `#${index + 1}`),
                        h(NDivider, { dashed: true }),
                        h('div', symbol),
                    ]
                },
            },
            {
                title: 'Cost',
                key: 'amount',
                render: (rowData) => {
                    const [symbol, currency] = splitTradeSymbol(rowData.symbol)
                    const amount = `${formatAssetAmount(rowData.amount)} ${symbol}`
                    const cost = `${formatFixed(rowData.cost)} ${currency}`
                    return [
                        h('div', amount),
                        h(NDivider, { dashed: true }),
                        h('div', cost),
                    ]
                },
            },
            {
                title: 'PNL',
                key: 'profit',
                render: (rowData) => {
                    const [, currency] = splitTradeSymbol(rowData.symbol)
                    const profitPercent =
                        `${formatFixed(rowData.profit_percent)} %`
                    const pnl = `${formatFixed(rowData.profit)} ${currency}`
                    return [
                        h('div', { class: 'profit' }, profitPercent),
                        h(NDivider, { dashed: true }),
                        h('div', pnl),
                    ]
                },
            },
            {
                title: 'TP/SO',
                key: 'tp_price',
                render: (rowData) => {
                    const avgPrice = rowData.avg_price
                    const tpPrice = rowData.tp_price
                    const currentPrice = rowData.current_price
                    const minPrice = avgPrice - (avgPrice / 100) * 0.7
                    const maxPrice = (tpPrice / 100) * 0.7 + Number(tpPrice)
                    const fillColor =
                        currentPrice < avgPrice
                            ? 'rgb(224, 108, 117)'
                            : 'rgb(99, 226, 183)'
                    return [
                        h(NSlider, {
                            value: [currentPrice, avgPrice],
                            range: true,
                            min: minPrice,
                            max: maxPrice,
                            disabled: true,
                            themeOverrides: {
                                fillColor,
                                handleSize: '8px',
                                opacityDisabled: '1',
                            },
                        }),
                        h(NDivider, { dashed: true }),
                        h('div', String(getSafetyOrderCount(rowData))),
                    ]
                },
                align: 'center',
            },
            {
                title: 'Action',
                key: 'action',
                render: (rowData) => {
                    if (isUnsellableRemainder(rowData)) {
                        return [
                            h(NTooltip, {}, {
                                trigger: () =>
                                    h(
                                        NButton,
                                        {
                                            type: 'error',
                                            size: 'medium',
                                            ghost: true,
                                            style: tradeActionButtonStyle,
                                            onClick: () =>
                                                options.onDealStop(rowData),
                                        },
                                        { default: () => 'Stop (Unsellable)' },
                                    ),
                                default: () => getUnsellableMessage(rowData),
                            }),
                        ]
                    }
                    return [
                        h(NButtonGroup, { size: 'medium', vertical: true }, {
                            default: () => [
                                h(
                                    NButton,
                                    {
                                        primary: true,
                                        size: 'medium',
                                        ghost: true,
                                        color: '#63e2b7',
                                        style: tradeActionButtonStyle,
                                        onClick: () =>
                                            options.onDealSell(rowData),
                                    },
                                    { default: () => 'Sell' },
                                ),
                                h(
                                    NButton,
                                    {
                                        primary: true,
                                        size: 'medium',
                                        ghost: true,
                                        color: '#63e2b7',
                                        style: tradeActionButtonStyle,
                                        onClick: () =>
                                            options.onDealBuy(rowData),
                                    },
                                    { default: () => 'Buy' },
                                ),
                                h(
                                    NButton,
                                    {
                                        primary: true,
                                        size: 'medium',
                                        ghost: true,
                                        color: '#63e2b7',
                                        style: tradeActionButtonStyle,
                                        onClick: () =>
                                            options.onDealStop(rowData),
                                    },
                                    { default: () => 'Stop' },
                                ),
                            ],
                        }),
                    ]
                },
                align: 'center',
            },
            {
                title: 'Opened',
                key: 'open_date',
                align: 'center',
                render: (rowData) => {
                    const { date, time } = resolveTradeDateTime(
                        rowData.open_date,
                    )
                    return [
                        h('div', date),
                        h(NDivider, { dashed: true }),
                        h('div', time),
                    ]
                },
            },
        ]

        if (options.isMobile.value) {
            return columns.filter((column) => {
                if (!('key' in column)) {
                    return true
                }
                return ['symbol', 'profit', 'action'].includes(
                    String(column.key),
                )
            })
        }

        if (options.isTablet.value) {
            return columns.filter((column) => {
                if (!('key' in column)) {
                    return true
                }
                return ['symbol', 'amount', 'profit', 'action', 'open_date']
                    .includes(String(column.key))
            })
        }

        return columns
    }

    const columnsOpenTrades = computed(() => columnsTrades())

    return {
        columnsOpenTrades,
        renderExpandIcon,
        rowClasses,
    }
}
