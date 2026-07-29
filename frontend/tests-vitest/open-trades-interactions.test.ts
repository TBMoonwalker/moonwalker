import { mount } from '@vue/test-utils'
import {
    defineComponent,
    h,
    type PropType,
    type VNode,
} from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import OpenTrades from '../src/components/OpenTrades.vue'
import type { OpenTradeRow } from '../src/helpers/openTrades'

const testState = vi.hoisted(() => ({
    isMobile: true,
    rows: [] as OpenTradeRow[],
}))
const loadConfiguredMinTimeframeMock = vi.hoisted(() => vi.fn())

vi.mock('pinia', async (importOriginal) => {
    const actual = await importOriginal<typeof import('pinia')>()
    return {
        ...actual,
        storeToRefs: () => ({
            data: { value: { funds_available: 500 } },
        }),
    }
})

vi.mock('../src/stores/websocket', () => ({
    useWebSocketDataStore: () => ({}),
}))

vi.mock('../src/stores/trades', () => ({
    useTradesStore: () => ({
        openTrades: testState.rows,
        setOpenTrades: vi.fn(),
    }),
}))

vi.mock('../src/control-center/configSnapshotStore', () => ({
    useSharedConfigSnapshot: () => ({
        snapshot: { value: { mstc: 5 } },
    }),
}))

vi.mock('../src/composables/useTradeTableFeed', () => ({
    useTradeTableFeed: () => ({
        rows: { value: testState.rows },
        isTableLoading: { value: false },
        tableEmptyText: { value: 'No open trades' },
    }),
}))

vi.mock('../src/composables/useViewport', () => ({
    useViewport: () => ({
        isMobile: { value: testState.isMobile },
        isTablet: { value: false },
    }),
}))

vi.mock('../src/composables/useConfiguredMinTimeframe', () => ({
    useConfiguredMinTimeframe: () => ({
        configuredMinTimeframe: {
            value: { timerange: '4h', seconds: 14_400 },
        },
        loadConfiguredMinTimeframe: loadConfiguredMinTimeframeMock,
    }),
}))

vi.mock('../src/composables/useOpenTradeActions', () => ({
    useOpenTradeActions: () => ({
        handleAddManualBuy: vi.fn(),
        handleDealSell: vi.fn(),
        handleDealStop: vi.fn(),
    }),
}))

vi.mock('../src/composables/useMissionPauseActions', () => ({
    useMissionPauseActions: () => ({
        handlePauseMission: vi.fn(),
        handleResumeMission: vi.fn(),
        isMissionActionLoading: () => false,
        missionActionErrors: {},
    }),
}))

vi.mock('naive-ui/es/dialog', () => ({
    useDialog: () => ({ warning: vi.fn() }),
}))

vi.mock('naive-ui/es/message', () => ({
    useMessage: () => ({
        error: vi.fn(),
        success: vi.fn(),
    }),
}))

const DataTableStub = defineComponent({
    name: 'NDataTable',
    props: {
        columns: {
            type: Array as PropType<Array<Record<string, unknown>>>,
            default: () => [],
        },
        data: {
            type: Array as PropType<OpenTradeRow[]>,
            default: () => [],
        },
        rowKey: {
            type: Function as PropType<(row: OpenTradeRow) => string | number>,
            required: true,
        },
        rowProps: {
            type: Function as PropType<
                (row: OpenTradeRow) => Record<string, unknown>
            >,
            required: true,
        },
        expandedRowKeys: {
            type: Array as PropType<Array<string | number>>,
            default: () => [],
        },
    },
    setup(props) {
        return () =>
            h(
                'div',
                { 'data-test': 'data-table' },
                props.data.map((row) => {
                    const key = props.rowKey(row)
                    const children: VNode[] = [
                        h('span', { 'data-test': 'row-content' }, row.symbol),
                    ]
                    if (props.expandedRowKeys.includes(key)) {
                        const replayColumn = props.columns.find(
                            (column) => column.type === 'expand',
                        )
                        const renderExpand = replayColumn?.renderExpand as
                            | ((rowData: OpenTradeRow) => VNode)
                            | undefined
                        children.push(
                            h(
                                'div',
                                { 'data-test': 'expanded-detail' },
                                renderExpand?.(row),
                            ),
                        )
                    }
                    return h(
                        'div',
                        {
                            ...props.rowProps(row),
                            key,
                            'data-test': 'trade-row',
                        },
                        children,
                    )
                }),
            )
    },
})

const ExpandedRowStub = defineComponent({
    name: 'OpenTradeExpandedRow',
    setup: () => () => h('div', { 'data-test': 'expanded-replay' }),
})

function openTrade(): OpenTradeRow {
    return {
        id: 2,
        symbol: 'SEI/USDC',
        deal_id: 'deal-2',
        amount: 1_155.30142,
        cost: 56.804204,
        profit: -8,
        profit_percent: -14,
        current_price: 0.042,
        tp_price: 0.0502,
        avg_price: 0.0492,
        so_count: 1,
        open_date: '2026-07-10T01:30:18Z',
        baseorder: {
            id: 1,
            timestamp: '2026-07-10T01:30:18Z',
            ordersize: 13.806624,
            amount: 270.14312,
            symbol: 'SEI/USDC',
            price: 0.05106,
        },
        safetyorder: [
            {
                id: 2,
                timestamp: '2026-07-14T23:21:39Z',
                ordersize: 42.99758,
                amount: 885.1583,
                symbol: 'SEI/USDC',
                price: 0.04853,
            },
        ],
        precision: 5,
    }
}

function mountOpenTrades() {
    return mount(OpenTrades, {
        global: {
            stubs: {
                NDataTable: DataTableStub,
                DataTable: DataTableStub,
                OpenTradeExpandedRow: ExpandedRowStub,
            },
        },
    })
}

describe('OpenTrades mobile replay interaction', () => {
    beforeEach(() => {
        testState.isMobile = true
        testState.rows = [openTrade()]
        loadConfiguredMinTimeframeMock.mockReset()
        loadConfiguredMinTimeframeMock.mockResolvedValue(undefined)
    })

    it('retains the expand column and mounts replay details after a row click', async () => {
        const wrapper = mountOpenTrades()
        const row = wrapper.get('[data-test="trade-row"]')
        const columns = wrapper
            .getComponent(DataTableStub)
            .props('columns') as Array<Record<string, unknown>>

        expect(columns[0].type).toBe('expand')
        expect(row.attributes('aria-expanded')).toBe('false')
        expect(wrapper.find('[data-test="expanded-replay"]').exists()).toBe(false)

        await row.get('[data-test="row-content"]').trigger('click')

        expect(row.attributes('aria-expanded')).toBe('true')
        expect(wrapper.get('[data-test="expanded-replay"]').exists()).toBe(true)
    })
})
