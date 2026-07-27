import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import WaitingCampaignExpandedRow from '../src/components/WaitingCampaignExpandedRow.vue'
import type { WaitingCampaignRow } from '../src/stores/trades'

const fetchJsonMock = vi.hoisted(() => vi.fn())

vi.mock('../src/api/client', () => ({
    fetchJson: fetchJsonMock,
}))

const CAMPAIGN_ID = '33333333-3333-4333-8333-333333333333'
const DEAL_ID = '11111111-1111-4111-8111-111111111111'

const TradeReplayChartStub = defineComponent({
    name: 'TradeReplayChartStub',
    props: {
        campaignId: { type: String, default: null },
    },
    setup: () => () => h('div', { 'data-test': 'replay-chart' }),
})

function waitingRow(): WaitingCampaignRow {
    return {
        id: 7,
        key: 7,
        symbol: 'BTC/USDC',
        deal_id: DEAL_ID,
        campaign_id: CAMPAIGN_ID,
        campaign_started_at: '2026-07-01T10:00:00Z',
        lifecycle_mode: 'sidestep_reentry',
        exposure_state: 'flat_waiting_reentry',
        amount: 0,
        cost: 0,
        profit: 0,
        profit_percent: 0,
        current_price: 98,
        tp_price: 0,
        avg_price: 0,
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
    }
}

describe('Waiting campaign replay indicators', () => {
    beforeEach(() => {
        fetchJsonMock.mockReset()
        fetchJsonMock.mockResolvedValue({ result: [] })
    })

    it('passes campaign context to execution and indicator replay', async () => {
        const wrapper = mount(WaitingCampaignExpandedRow, {
            props: {
                rowData: waitingRow(),
                minTimeframe: { timerange: '15min', seconds: 900 },
            },
            global: {
                stubs: {
                    TradeReplayChart: TradeReplayChartStub,
                },
            },
        })

        await flushPromises()

        expect(fetchJsonMock).toHaveBeenCalledWith(
            `/trades/executions/${DEAL_ID}?campaign_id=${CAMPAIGN_ID}`,
        )
        expect(
            wrapper.getComponent(TradeReplayChartStub).props('campaignId'),
        ).toBe(CAMPAIGN_ID)
    })
})
