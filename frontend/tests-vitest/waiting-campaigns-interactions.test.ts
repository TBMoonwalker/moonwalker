import { mount } from '@vue/test-utils'
import {
    defineComponent,
    h,
    nextTick,
    type PropType,
    type VNode,
} from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import WaitingCampaigns from '../src/components/WaitingCampaigns.vue'
import type { WaitingCampaignRow } from '../src/stores/trades'

const testState = vi.hoisted(() => ({
    isMobile: true,
    rows: [] as WaitingCampaignRow[],
}))
const loadConfiguredMinTimeframeMock = vi.hoisted(() => vi.fn())

vi.mock('../src/stores/trades', () => ({
    useTradesStore: () => ({
        waitingCampaigns: testState.rows,
        setWaitingCampaigns: vi.fn(),
    }),
}))

vi.mock('../src/composables/useTradeTableFeed', () => ({
    useTradeTableFeed: () => ({
        rows: { value: testState.rows },
        isTableLoading: { value: false },
        tableEmptyText: { value: 'No waiting campaigns' },
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
            value: { timerange: '30min', seconds: 1_800 },
        },
        loadConfiguredMinTimeframe: loadConfiguredMinTimeframeMock,
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
            type: Array as PropType<WaitingCampaignRow[]>,
            default: () => [],
        },
        rowKey: {
            type: Function as PropType<(row: WaitingCampaignRow) => string | number>,
            required: true,
        },
        rowProps: {
            type: Function as PropType<
                (row: WaitingCampaignRow) => Record<string, unknown>
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
                {
                    'data-test': 'data-table',
                    'data-column-count': props.columns.length,
                },
                props.data.map((row) => {
                    const key = props.rowKey(row)
                    const children: VNode[] = [
                        h('span', { 'data-test': 'row-content' }, row.symbol),
                        h(
                            'button',
                            {
                                type: 'button',
                                'data-test': 'interactive-child',
                            },
                            'Safe child',
                        ),
                    ]
                    if (props.expandedRowKeys.includes(key)) {
                        const replayColumn = props.columns.find(
                            (column) => column.type === 'expand',
                        )
                        const renderExpand = replayColumn?.renderExpand as
                            | ((rowData: WaitingCampaignRow) => VNode)
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
                            'data-test': 'campaign-row',
                            'data-row-key': String(key),
                        },
                        children,
                    )
                }),
            )
    },
})

const ExpandedRowStub = defineComponent({
    name: 'WaitingCampaignExpandedRow',
    props: {
        rowData: { type: Object, required: true },
        minTimeframe: { type: Object, required: true },
    },
    setup: () => () => h('div', { 'data-test': 'expanded-chart' }),
})

function waitingRow(
    overrides: Partial<WaitingCampaignRow> = {},
): WaitingCampaignRow {
    return {
        id: 7,
        key: 7,
        symbol: 'BTC/USDC',
        deal_id: 'deal-7',
        campaign_id: 'campaign-7',
        campaign_started_at: '2026-07-01T10:00:00Z',
        lifecycle_mode: 'sidestep_reentry',
        exposure_state: 'waiting_reentry',
        amount: 1,
        cost: 100,
        profit: 0,
        profit_percent: 0,
        current_price: 98,
        tp_price: 102,
        avg_price: 100,
        so_count: 0,
        open_date: '2026-07-01T09:00:00Z',
        baseorder: {
            id: 1,
            timestamp: '2026-07-01T09:00:00Z',
            ordersize: 100,
            amount: 1,
            symbol: 'BTC/USDC',
            price: 100,
        },
        safetyorder: [],
        precision: 2,
        waiting_reference_price: 101,
        ...overrides,
    }
}

function mountWaitingCampaigns() {
    return mount(WaitingCampaigns, {
        global: {
            stubs: {
                NDataTable: DataTableStub,
                DataTable: DataTableStub,
                WaitingCampaignExpandedRow: ExpandedRowStub,
            },
        },
    })
}

describe('WaitingCampaigns row interactions', () => {
    beforeEach(() => {
        testState.isMobile = true
        testState.rows = [waitingRow()]
        loadConfiguredMinTimeframeMock.mockReset()
        loadConfiguredMinTimeframeMock.mockResolvedValue(undefined)
    })

    it('expands and collapses from non-interactive row clicks', async () => {
        const wrapper = mountWaitingCampaigns()
        const row = wrapper.get('[data-test="campaign-row"]')

        expect(row.attributes('aria-expanded')).toBe('false')
        expect(wrapper.find('[data-test="expanded-detail"]').exists()).toBe(false)

        await row.get('[data-test="row-content"]').trigger('click')
        expect(row.attributes('aria-expanded')).toBe('true')
        expect(wrapper.get('[data-test="expanded-chart"]').exists()).toBe(true)

        await row.get('[data-test="row-content"]').trigger('click')
        expect(row.attributes('aria-expanded')).toBe('false')
        expect(wrapper.find('[data-test="expanded-detail"]').exists()).toBe(false)
    })

    it('supports Enter and Space while ignoring unrelated keys', async () => {
        const wrapper = mountWaitingCampaigns()
        const row = wrapper.get('[data-test="campaign-row"]')

        const unrelated = new KeyboardEvent('keydown', {
            key: 'ArrowRight',
            bubbles: true,
            cancelable: true,
        })
        row.element.dispatchEvent(unrelated)
        await nextTick()
        expect(unrelated.defaultPrevented).toBe(false)
        expect(row.attributes('aria-expanded')).toBe('false')

        const enter = new KeyboardEvent('keydown', {
            key: 'Enter',
            bubbles: true,
            cancelable: true,
        })
        row.element.dispatchEvent(enter)
        await nextTick()
        expect(enter.defaultPrevented).toBe(true)
        expect(row.attributes('aria-expanded')).toBe('true')

        const space = new KeyboardEvent('keydown', {
            key: ' ',
            bubbles: true,
            cancelable: true,
        })
        row.element.dispatchEvent(space)
        await nextTick()
        expect(space.defaultPrevented).toBe(true)
        expect(row.attributes('aria-expanded')).toBe('false')
    })

    it('does not expand when an interactive descendant receives the click', async () => {
        const wrapper = mountWaitingCampaigns()
        const row = wrapper.get('[data-test="campaign-row"]')

        await row.get('[data-test="interactive-child"]').trigger('click')

        expect(row.attributes('aria-expanded')).toBe('false')
        expect(wrapper.find('[data-test="expanded-detail"]').exists()).toBe(false)
    })

    it('uses stable row-key fallbacks and mobile replay columns', () => {
        testState.rows = [
            waitingRow(),
            waitingRow({
                id: 8,
                key: 8,
                deal_id: null,
                campaign_id: 'campaign-8',
            }),
            waitingRow({
                id: 9,
                key: 9,
                deal_id: null,
                campaign_id: null,
            }),
        ]
        const wrapper = mountWaitingCampaigns()
        const rows = wrapper.findAll('[data-test="campaign-row"]')
        const table = wrapper.getComponent(DataTableStub)
        const columns = table.props('columns') as Array<Record<string, unknown>>
        const replayVNode = (
            columns[0].renderExpand as (row: WaitingCampaignRow) => VNode
        )(testState.rows[0])

        expect(rows.map((row) => row.attributes('data-row-key'))).toEqual([
            'deal-7',
            'campaign-8',
            '9',
        ])
        expect(columns).toHaveLength(2)
        expect(columns[0].type).toBe('expand')
        expect(replayVNode.props?.minTimeframe).toEqual({
            timerange: '30min',
            seconds: 1_800,
        })
        expect(loadConfiguredMinTimeframeMock).toHaveBeenCalledOnce()
    })

    it('keeps the replay expansion column on desktop', () => {
        testState.isMobile = false
        const wrapper = mountWaitingCampaigns()
        const columns = wrapper
            .getComponent(DataTableStub)
            .props('columns') as Array<Record<string, unknown>>

        expect(columns).toHaveLength(8)
        expect(columns[0].type).toBe('expand')
        expect(columns.slice(1).map((column) => column.key)).toEqual([
            'symbol',
            'waiting_reference_quote',
            'display_profit_percent',
            'waiting_reference_price',
            'reentry_status',
            'action',
            'open_date',
        ])
    })
})
