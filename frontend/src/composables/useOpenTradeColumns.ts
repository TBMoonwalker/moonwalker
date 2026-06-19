import { computed, h, type Ref } from 'vue'
import { NButton } from 'naive-ui/es/button'
import { NDropdown } from 'naive-ui/es/dropdown'
import { NIcon } from 'naive-ui/es/icon'
import { NTag } from 'naive-ui/es/tag'
import { NTooltip } from 'naive-ui/es/tooltip'
import { type DataTableColumns } from 'naive-ui/es/data-table'
import { EllipsisHorizontal } from '@vicons/ionicons5'

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
    onDealSell: (rowData: OpenTradeRow) => void
    onDealStop: (rowData: OpenTradeRow) => void
    onPauseMission: (rowData: OpenTradeRow) => void | Promise<void>
    onResumeMission: (rowData: OpenTradeRow) => void | Promise<void>
    sortState: Ref<TradeTableSortState | null>
    maxSafetyOrders: Ref<number>
}

const tradeActionButtonStyle = {
    minHeight: '36px',
    minWidth: '48px',
    padding: '0 11px',
}
const TPSO_PRICE_PADDING_PERCENT = 0.7
const MIN_TPSO_STATUS_FILL_PERCENT = 3

function clampPercent(value: number): number {
    if (!Number.isFinite(value)) {
        return 0
    }
    return Math.max(0, Math.min(100, value))
}

function resolveRangePercent(value: number, min: number, max: number): number {
    const range = max - min
    if (!Number.isFinite(range) || range <= 0) {
        return 0
    }
    return clampPercent(((value - min) / range) * 100)
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
        const automationAction = rowData.automation_paused ? 'resume' : 'pause'
        return h(
            NDropdown,
            {
                trigger: 'click',
                options: [
                    {
                        key: automationAction,
                        label: rowData.automation_paused
                            ? 'Resume automation'
                            : 'Pause automation',
                        disabled: options.isMissionActionLoading(
                            rowData.symbol,
                            automationAction,
                        ),
                    },
                    {
                        key: 'manual-buy',
                        label: 'Add manual buy',
                        disabled: isBuyBlocked(rowData),
                    },
                ],
                onSelect: (key: string | number) => {
                    if (key === 'resume') {
                        void options.onResumeMission(rowData)
                        return
                    }
                    if (key === 'pause') {
                        void options.onPauseMission(rowData)
                        return
                    }
                    if (key === 'manual-buy') {
                        options.onAddManualBuy(rowData)
                        return
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

    function renderCellStack(
        main: string,
        secondary?: string,
        mainClass = 'trade-cell-main',
    ) {
        return h('div', { class: 'trade-cell-stack' }, [
            h('span', { class: mainClass }, main),
            secondary
                ? h('span', { class: 'trade-cell-sub' }, secondary)
                : null,
        ])
    }

    function renderSymbolCell(rowData: OpenTradeRow, index: number) {
        const [symbol, currency] = splitTradeSymbol(rowData.symbol)
        const reentryLabel = getReentryLabel(rowData)
        const tags = []
        if (reentryLabel) {
            tags.push(
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
            tags.push(
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
        return h('div', { class: 'trade-symbol-cell' }, [
            h('span', { class: 'trade-symbol-main' }, `${symbol}/${currency}`),
            h('div', { class: 'trade-symbol-meta' }, [
                h('span', { class: 'trade-cell-sub' }, `#${index + 1}`),
                tags.length
                    ? h('div', { class: 'trade-cell-tags' }, tags)
                    : null,
            ]),
        ])
    }

    function renderTpSoCell(rowData: OpenTradeRow) {
        const safetyOrderCount = getSafetyOrderCount(rowData)
        const maxSafetyOrders = Math.max(
            safetyOrderCount,
            Math.trunc(Number(options.maxSafetyOrders.value) || 0),
        )
        const avgPrice = Number(rowData.avg_price)
        const tpPrice = Number(rowData.tp_price)
        const currentPrice = Number(rowData.current_price)
        const hasPriceStatus =
            avgPrice > 0 && tpPrice > 0 && currentPrice > 0
        const minPrice =
            avgPrice - (avgPrice / 100) * TPSO_PRICE_PADDING_PERCENT
        const maxPrice =
            tpPrice + (tpPrice / 100) * TPSO_PRICE_PADDING_PERCENT
        const avgPercent = resolveRangePercent(avgPrice, minPrice, maxPrice)
        const currentPercent = resolveRangePercent(
            currentPrice,
            minPrice,
            maxPrice,
        )
        const fillStart = hasPriceStatus
            ? Math.min(avgPercent, currentPercent)
            : 0
        const fillWidth = hasPriceStatus
            ? Math.max(
                  Math.abs(currentPercent - avgPercent),
                  MIN_TPSO_STATUS_FILL_PERCENT,
              )
            : 0
        const toneClass = !hasPriceStatus
            ? 'is-idle'
            : currentPrice < avgPrice
              ? 'is-warning'
              : 'is-active'
        const label = maxSafetyOrders
            ? `SO ${safetyOrderCount} / ${maxSafetyOrders}`
            : `SO ${safetyOrderCount}`

        return h('div', { class: ['trade-tpso-cell', toneClass] }, [
            h('div', { class: 'trade-tpso-track' }, [
                h('span', {
                    class: 'trade-tpso-fill',
                    style: {
                        left: `${fillStart}%`,
                        width: `${fillWidth}%`,
                    },
                }),
            ]),
            h('span', { class: 'trade-progress-label' }, label),
        ])
    }

    function columnsTrades(): DataTableColumns<OpenTradeRow> {
        const columns: DataTableColumns<OpenTradeRow> = [
            {
                type: 'expand',
                width: 0,
                minWidth: 0,
                maxWidth: 0,
                className: 'trade-hidden-expand-cell',
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
                render: (rowData, index) => renderSymbolCell(rowData, index),
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
                    return renderCellStack(amount, cost)
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
                        `${formatFixed(getDisplayedProfitPercent(rowData))}%`
                    const pnl = `${formatFixed(getDisplayedProfit(rowData))} ${currency}`
                    return renderCellStack(
                        profitPercent,
                        pnl,
                        'trade-cell-main profit',
                    )
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
                render: (rowData) => renderTpSoCell(rowData),
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
                    const compactActions = h(
                        'div',
                        { class: 'trade-row-actions' },
                        [
                            h(
                                NButton,
                                {
                                    primary: true,
                                    size: 'medium',
                                    ghost: true,
                                    color: '#2E7D5B',
                                    style: tradeActionButtonStyle,
                                    onClick: () => options.onDealSell(rowData),
                                },
                                { default: () => 'Sell' },
                            ),
                            h(
                                NButton,
                                {
                                    type: 'error',
                                    size: 'medium',
                                    ghost: true,
                                    style: tradeActionButtonStyle,
                                    onClick: () => options.onDealStop(rowData),
                                },
                                { default: () => 'Stop' },
                            ),
                            renderOverflowActions(rowData),
                        ],
                    )
                    return [
                        compactActions,
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
                    return renderCellStack(date, time)
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
        rowClasses,
    }
}
