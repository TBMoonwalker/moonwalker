import { computed, h, type Ref } from 'vue'
import { NButton } from 'naive-ui/es/button'
import { NButtonGroup } from 'naive-ui/es/button-group'
import { NDivider } from 'naive-ui/es/divider'
import { NDropdown } from 'naive-ui/es/dropdown'
import { NIcon } from 'naive-ui/es/icon'
import { NSlider } from 'naive-ui/es/slider'
import { NTag } from 'naive-ui/es/tag'
import { NTooltip } from 'naive-ui/es/tooltip'
import { type DataTableColumns } from 'naive-ui/es/data-table'
import {
    ArrowForwardCircleOutline,
    EllipsisHorizontal,
} from '@vicons/ionicons5'

import OpenTradeExpandedRow from '../components/OpenTradeExpandedRow.vue'
import {
    OPEN_TRADES_MOBILE_COLUMN_KEYS,
    OPEN_TRADES_TABLET_COLUMN_KEYS,
    formatAssetAmount,
    formatFixed,
    resolveTradeTableColumnOrder,
    resolveTradeDateTime,
    shouldShowTradeTableColumn,
    type TradeTableSortState,
} from '../helpers/tradeTable'
import {
    getOpenTradeOpenedAt,
    getSafetyOrderCount,
    getUnsellableMessage,
    isUnsellableRemainder,
    splitTradeSymbol,
    type OpenTradeRow,
    type TimeframeChoice,
} from '../helpers/openTrades'

interface UseOpenTradeColumnsOptions {
    configuredMinTimeframe: Ref<TimeframeChoice>
    globalTradingPaused: Ref<boolean>
    isMobile: Ref<boolean>
    isMissionActionLoading: (
        symbol: string,
        action: 'pause' | 'resume',
    ) => boolean
    isTablet: Ref<boolean>
    missionActionErrors: Record<string, string | null>
    onAddManualBuy: (rowData: OpenTradeRow) => void
    onDealBuy: (rowData: OpenTradeRow) => void
    onDealSell: (rowData: OpenTradeRow) => void
    onDealStop: (rowData: OpenTradeRow) => void
    onPauseMission: (rowData: OpenTradeRow) => void | Promise<void>
    onResumeMission: (rowData: OpenTradeRow) => void | Promise<void>
    sortState: Ref<TradeTableSortState | null>
}

const tradeActionButtonStyle = {
    minHeight: '44px',
    minWidth: '56px',
    padding: '0 12px',
}

export function useOpenTradeColumns(options: UseOpenTradeColumnsOptions) {
    function resolveActionError(rowData: OpenTradeRow): string | null {
        return options.missionActionErrors[String(rowData.symbol)] ?? null
    }

    function isBuyBlocked(rowData: OpenTradeRow): boolean {
        return (
            Boolean(rowData.automation_paused) ||
            Boolean(options.globalTradingPaused.value)
        )
    }

    function renderOverflowActions(rowData: OpenTradeRow) {
        return h(
            NDropdown,
            {
                trigger: 'click',
                options: [
                    {
                        key: 'buy',
                        label: 'Buy',
                        disabled: isBuyBlocked(rowData),
                    },
                    {
                        key: 'stop',
                        label: 'Stop',
                    },
                    {
                        key: rowData.automation_paused
                            ? 'resume'
                            : 'pause',
                        label: rowData.automation_paused
                            ? 'Resume automation'
                            : 'Pause automation',
                    },
                ],
                onSelect: (key: string | number) => {
                    if (key === 'buy') {
                        options.onDealBuy(rowData)
                        return
                    }
                    if (key === 'stop') {
                        options.onDealStop(rowData)
                        return
                    }
                    if (key === 'resume') {
                        options.onResumeMission(rowData)
                        return
                    }
                    if (key === 'pause') {
                        options.onPauseMission(rowData)
                    }
                },
            },
            {
                default: () =>
                    h(
                        NButton,
                        {
                            size: 'medium',
                            ghost: true,
                            style: tradeActionButtonStyle,
                        },
                        {
                            icon: () =>
                                h(
                                    NIcon,
                                    { size: 18 },
                                    {
                                        default: () => h(EllipsisHorizontal),
                                    },
                                ),
                            default: () => 'More',
                        },
                    ),
            },
        )
    }

    function getDisplayedProfit(rowData: OpenTradeRow): number {
        return Number(rowData.display_profit ?? rowData.profit ?? 0)
    }

    function getDisplayedProfitPercent(rowData: OpenTradeRow): number {
        return Number(
            rowData.display_profit_percent ?? rowData.profit_percent ?? 0,
        )
    }

    function rowClasses(row: OpenTradeRow): string {
        if (Math.sign(getDisplayedProfitPercent(row)) >= 0) {
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

    function getReentryLabel(rowData: OpenTradeRow): string | null {
        const sidestepCount = Number(rowData.sidestep_count ?? 0)
        if (
            String(rowData.lifecycle_mode ?? '') !== 'sidestep_reentry' ||
            sidestepCount <= 0
        ) {
            return null
        }
        return `Re-entered x${sidestepCount}`
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
                    const reentryLabel = getReentryLabel(rowData)
                    const rows = [
                        h('div', `#${index + 1}`),
                        h(NDivider, { dashed: true }),
                        h('div', symbol),
                    ]
                    if (reentryLabel) {
                        rows.push(h(NDivider, { dashed: true }))
                        rows.push(
                            h(
                                NTag,
                                {
                                    size: 'small',
                                    bordered: false,
                                    type: 'warning',
                                },
                                { default: () => reentryLabel },
                            ),
                        )
                    }
                    if (rowData.automation_paused) {
                        rows.push(h(NDivider, { dashed: true }))
                        rows.push(
                            h(
                                NTag,
                                {
                                    size: 'small',
                                    bordered: false,
                                    type: 'warning',
                                },
                                { default: () => 'Automation paused' },
                            ),
                        )
                    }
                    return rows
                },
                sorter: true,
                sortOrder: resolveTradeTableColumnOrder(
                    options.sortState.value,
                    'symbol',
                ),
            },
            {
                title: 'Cost',
                key: 'cost',
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
                sorter: true,
                sortOrder: resolveTradeTableColumnOrder(
                    options.sortState.value,
                    'cost',
                ),
            },
            {
                title: 'PNL',
                key: 'display_profit_percent',
                render: (rowData) => {
                    const [, currency] = splitTradeSymbol(rowData.symbol)
                    const profitPercent =
                        `${formatFixed(getDisplayedProfitPercent(rowData))} %`
                    const pnl = `${formatFixed(getDisplayedProfit(rowData))} ${currency}`
                    return [
                        h('div', { class: 'profit' }, profitPercent),
                        h(NDivider, { dashed: true }),
                        h('div', pnl),
                    ]
                },
                sorter: true,
                sortOrder: resolveTradeTableColumnOrder(
                    options.sortState.value,
                    'display_profit_percent',
                ),
            },
            {
                title: 'TP/SO',
                key: 'so_count',
                render: (rowData) => {
                    const avgPrice = rowData.avg_price
                    const tpPrice = rowData.tp_price
                    const currentPrice = rowData.current_price
                    const minPrice = avgPrice - (avgPrice / 100) * 0.7
                    const maxPrice = (tpPrice / 100) * 0.7 + Number(tpPrice)
                    const fillColor =
                        currentPrice < avgPrice
                              ? '#B4443F'
                              : '#2E7D5B'
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
                sorter: true,
                sortOrder: resolveTradeTableColumnOrder(
                    options.sortState.value,
                    'so_count',
                ),
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
                    const actionError = resolveActionError(rowData)
                    const pauseAction = rowData.automation_paused
                        ? () => options.onResumeMission(rowData)
                        : () => options.onPauseMission(rowData)
                    const pauseActionLabel = rowData.automation_paused
                        ? 'Resume automation'
                        : 'Pause automation'
                    const pauseActionLoading = options.isMissionActionLoading(
                        rowData.symbol,
                        rowData.automation_paused ? 'resume' : 'pause',
                    )
                    const desktopActions = h(
                        NButtonGroup,
                        { size: 'medium', vertical: true },
                        {
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
                                        disabled: isBuyBlocked(rowData),
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
                                h(
                                    NButton,
                                    {
                                        type: 'warning',
                                        ghost: !rowData.automation_paused,
                                        size: 'medium',
                                        style: tradeActionButtonStyle,
                                        loading: pauseActionLoading,
                                        onClick: pauseAction,
                                    },
                                    { default: () => pauseActionLabel },
                                ),
                            ],
                        },
                    )
                    const compactActions = h(
                        'div',
                        {
                            style: 'display:flex; justify-content:center; gap:8px;',
                        },
                        [
                            h(
                                NButton,
                                {
                                    primary: true,
                                    size: 'medium',
                                    ghost: true,
                                    color: '#63e2b7',
                                    style: tradeActionButtonStyle,
                                    onClick: () => options.onDealSell(rowData),
                                },
                                { default: () => 'Sell' },
                            ),
                            renderOverflowActions(rowData),
                        ],
                    )
                    return [
                        options.isMobile.value || options.isTablet.value
                            ? compactActions
                            : desktopActions,
                        actionError
                            ? h(
                                  'div',
                                  {
                                      style: 'margin-top:8px; max-width:220px; font-size:12px; color:#B4443F; text-wrap:pretty;',
                                  },
                                  actionError,
                              )
                            : null,
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
                        getOpenTradeOpenedAt(rowData),
                    )
                    return [
                        h('div', date),
                        h(NDivider, { dashed: true }),
                        h('div', time),
                    ]
                },
                sorter: true,
                sortOrder: resolveTradeTableColumnOrder(
                    options.sortState.value,
                    'open_date',
                ),
            },
        ]

        if (options.isMobile.value) {
            return columns.filter((column) => {
                if (!('key' in column)) {
                    return true
                }
                return shouldShowTradeTableColumn(
                    column.key,
                    OPEN_TRADES_MOBILE_COLUMN_KEYS,
                )
            })
        }

        if (options.isTablet.value) {
            return columns.filter((column) => {
                if (!('key' in column)) {
                    return true
                }
                return shouldShowTradeTableColumn(
                    column.key,
                    OPEN_TRADES_TABLET_COLUMN_KEYS,
                )
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
