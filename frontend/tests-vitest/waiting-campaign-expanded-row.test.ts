import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import WaitingCampaignExpandedRow from '../src/components/WaitingCampaignExpandedRow.vue'
import type {
    TradeExecutionRow,
    WaitingCampaignRow,
} from '../src/stores/trades'

const fetchJsonMock = vi.hoisted(() => vi.fn())

vi.mock('../src/api/client', () => ({
    fetchJson: fetchJsonMock,
}))

const TradeReplayChartStub = defineComponent({
    name: 'TradeReplayChartStub',
    props: {
        symbol: { type: String, required: true },
        precision: { type: Number, required: true },
        startTimestamp: { type: [Number, String], required: true },
        dealId: { type: String, default: null },
        minTimeframe: { type: Object, required: true },
        markers: { type: Array, required: true },
        priceLines: { type: Array, required: true },
    },
    setup: () => () => h('div', { 'data-test': 'replay-chart' }),
})

function waitingRow(
    overrides: Partial<WaitingCampaignRow> = {},
): WaitingCampaignRow {
    return {
        id: 7,
        key: 7,
        symbol: 'BTC/USDC',
        deal_id: null,
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
        last_transition_at: '2026-07-01T12:00:00Z',
        ...overrides,
    }
}

function execution(
    id: number,
    overrides: Partial<TradeExecutionRow>,
): TradeExecutionRow {
    return {
        id,
        deal_id: 'deal-7',
        symbol: 'BTC/USDC',
        side: 'buy',
        role: 'base_order',
        timestamp: `2026-07-01T${String(id).padStart(2, '0')}:00:00Z`,
        price: 100 + id,
        amount: 1,
        ordersize: 100,
        fee: 0,
        ...overrides,
    }
}

function mountExpandedRow(rowData: WaitingCampaignRow) {
    return mount(WaitingCampaignExpandedRow, {
        props: {
            rowData,
            minTimeframe: { timerange: '15min', seconds: 900 },
        },
        global: {
            stubs: {
                TradeReplayChart: TradeReplayChartStub,
            },
        },
    })
}

describe('WaitingCampaignExpandedRow', () => {
    beforeEach(() => {
        fetchJsonMock.mockReset()
    })

    afterEach(() => {
        vi.restoreAllMocks()
    })

    it('renders a sparse-history exit immediately without requesting executions', () => {
        const wrapper = mountExpandedRow(waitingRow())
        const chart = wrapper.getComponent(TradeReplayChartStub)

        expect(fetchJsonMock).not.toHaveBeenCalled()
        expect(chart.props('startTimestamp')).toBe('2026-07-01T10:00:00Z')
        expect(chart.props('markers')).toEqual([
            {
                timestamp: '2026-07-01T12:00:00Z',
                position: 'atPriceMiddle',
                price: 101,
                color: '#B4443F',
                shape: 'arrowDown',
                text: 'Exit',
            },
        ])
        expect(chart.props('priceLines')).toEqual([
            {
                price: 101,
                color: '#B4443F',
                lineStyle: 3,
                title: 'EXIT',
            },
        ])
    })

    it('uses empty sparse-history overlays and the final timestamp fallback', () => {
        vi.spyOn(Date, 'now').mockReturnValue(1_753_000_000_000)
        const wrapper = mountExpandedRow(
            waitingRow({
                campaign_started_at: null,
                open_date: undefined as unknown as string,
                last_transition_at: null,
                waiting_reference_price: 0,
            }),
        )
        const chart = wrapper.getComponent(TradeReplayChartStub)

        expect(chart.props('startTimestamp')).toBe(1_753_000_000_000)
        expect(chart.props('markers')).toEqual([])
        expect(chart.props('priceLines')).toEqual([])
    })

    it('waits for execution history and maps every marker and price-line role', async () => {
        let resolveRequest!: (value: unknown) => void
        fetchJsonMock.mockReturnValue(
            new Promise((resolve) => {
                resolveRequest = resolve
            }),
        )
        const wrapper = mountExpandedRow(
            waitingRow({ deal_id: 'deal-7' }),
        )

        expect(wrapper.findComponent(TradeReplayChartStub).exists()).toBe(false)
        expect(fetchJsonMock).toHaveBeenCalledWith('/trades/executions/deal-7')

        resolveRequest({
            result: [
                execution(7, {
                    timestamp: '2026-07-01T17:00:00Z',
                    side: 'sell',
                    role: 'sidestep_exit',
                    price: 0,
                }),
                execution(6, {
                    timestamp: '2026-07-01T16:00:00Z',
                    role: 'safety_order',
                    order_count: null,
                    price: 96,
                }),
                execution(5, {
                    timestamp: '2026-07-01T15:00:00Z',
                    role: 'safety_order',
                    order_count: 2,
                    price: 95,
                }),
                execution(4, {
                    timestamp: '2026-07-01T14:00:00Z',
                    role: 'base_order',
                    price: 99,
                }),
                execution(3, {
                    timestamp: '2026-07-01T13:00:00Z',
                    side: 'sell',
                    role: 'sidestep_exit',
                    price: 103,
                }),
                execution(2, {
                    timestamp: '2026-07-01T12:00:00Z',
                    role: 'manual_buy',
                    price: 102,
                }),
                execution(1, {
                    timestamp: '2026-07-01T11:00:00Z',
                    role: 'base_order',
                    price: 101,
                }),
            ],
        })
        await flushPromises()

        const chart = wrapper.getComponent(TradeReplayChartStub)
        expect(chart.props('startTimestamp')).toBe('2026-07-01T11:00:00Z')
        expect(chart.props('markers')).toMatchObject([
            { text: 'Buy', position: 'belowBar' },
            { text: 'Buy', position: 'belowBar' },
            { text: 'Exit', position: 'atPriceMiddle', price: 103 },
            { text: 'Re-entry', position: 'belowBar' },
            { text: 'Buy', position: 'belowBar' },
            { text: 'Buy', position: 'belowBar' },
            { text: 'Exit', position: 'aboveBar' },
        ])
        expect(chart.props('priceLines')).toMatchObject([
            { title: 'BO', price: 101 },
            { title: 'MANUAL', price: 102 },
            { title: 'EXIT1', price: 103 },
            { title: 'RE1', price: 99 },
            { title: 'SO2', price: 95 },
            { title: 'SO4', price: 96 },
        ])
    })

    it.each([
        ['a malformed response', () => Promise.resolve({ result: null })],
        ['a failed response', () => Promise.reject(new Error('offline'))],
    ])('falls back safely after %s', async (_label, buildResponse) => {
        fetchJsonMock.mockReturnValue(buildResponse())
        const wrapper = mountExpandedRow(
            waitingRow({
                deal_id: 'deal-7',
                waiting_reference_price: Number.NaN,
            }),
        )

        await flushPromises()

        const chart = wrapper.getComponent(TradeReplayChartStub)
        expect(chart.props('markers')).toMatchObject([
            {
                position: 'aboveBar',
                text: 'Exit',
            },
        ])
        expect(chart.props('priceLines')).toEqual([])
    })

    it('sorts legacy numeric timestamp strings before rendering', async () => {
        fetchJsonMock.mockResolvedValue({
            result: [
                execution(2, { timestamp: '1751371200000' }),
                execution(1, { timestamp: '1751367600000' }),
            ],
        })
        const wrapper = mountExpandedRow(
            waitingRow({ deal_id: 'deal-7' }),
        )

        await flushPromises()

        expect(
            wrapper
                .getComponent(TradeReplayChartStub)
                .props('startTimestamp'),
        ).toBe('1751367600000')
    })
})
