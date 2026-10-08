import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick } from 'vue'
import { beforeEach, describe, expect, it } from 'vitest'

import ConfigCapitalSection from '../src/components/config/ConfigCapitalSection.vue'
import { calculateCapitalBudgetPreview } from '../src/helpers/capitalBudgetPreview'
import { useWebSocketDataStore } from '../src/stores/websocket'

const draft = {
    baseOrderSize: 12,
    maxSafetyOrders: 5,
    reserveSafetyOrders: true,
    bufferPercent: 30,
    dynamicDcaEnabled: true,
    openTrades: Array.from({ length: 30 }, () => ({ so_count: 0 })),
}

describe('capital budget estimate', () => {
    beforeEach(() => setActivePinia(createPinia()))

    it('reconciles the live reserve separately from the admission buffer', () => {
        expect(calculateCapitalBudgetPreview(draft)).toMatchObject({
            openDealCount: 30,
            remainingSafetyOrders: 150,
            openDealReserve: 1800,
            newDealReserve: 60,
            newDealBuffer: 21.6,
            newDealRequirement: 93.6,
        })
    })

    it('accounts for used slots, exhausted ladders and unsellable dust', () => {
        expect(calculateCapitalBudgetPreview({
            ...draft,
            openTrades: [
                { so_count: 2 }, { so_count: 5 }, { so_count: 6 },
                { so_count: 0, unsellable_amount: 1, unsellable_reason: 'dust' },
            ],
        })).toMatchObject({ openDealCount: 3, remainingSafetyOrders: 3, openDealReserve: 36 })
    })

    it('keeps zero deals, unknown data and disabled reserve distinct', () => {
        expect(calculateCapitalBudgetPreview({ ...draft, openTrades: [] })?.openDealReserve).toBe(0)
        expect(calculateCapitalBudgetPreview({ ...draft, openTrades: null })?.openDealReserve).toBeNull()
        expect(calculateCapitalBudgetPreview({ ...draft, openTrades: [null] })?.openDealReserve).toBeNull()
        expect(calculateCapitalBudgetPreview({ ...draft, reserveSafetyOrders: false })).toMatchObject({
            openDealReserve: 0, newDealReserve: 0, newDealRequirement: 15.6,
        })
    })

    it.each([30, 0.3])('matches the backend buffer convention for %s', (bufferPercent) => {
        expect(calculateCapitalBudgetPreview({ ...draft, bufferPercent })?.newDealRequirement).toBe(93.6)
    })

    it('clamps a negative buffer to no buffer, matching the backend', () => {
        // normalize_buffer_pct clamps <= 0 to 0; a negative buffer is not a
        // preview error, it is simply no buffer.
        const noBuffer = calculateCapitalBudgetPreview({ ...draft, bufferPercent: -5 })
        expect(noBuffer?.newDealRequirement).toBe(72) // base 12 + reserve 60, no buffer
        expect(noBuffer?.newDealBuffer).toBe(0)
        expect(noBuffer?.bufferPercent).toBe(0)
    })

    it('does not invent estimates from missing or invalid draft amounts', () => {
        expect(calculateCapitalBudgetPreview({ ...draft, baseOrderSize: null })).toBeNull()
        expect(calculateCapitalBudgetPreview({ ...draft, baseOrderSize: Infinity })).toBeNull()
        expect(calculateCapitalBudgetPreview({ ...draft, maxSafetyOrders: 1.5 })).toBeNull()
        expect(calculateCapitalBudgetPreview({ ...draft, maxSafetyOrders: 0 })?.newDealReserve).toBe(0)
    })

    it('updates rendered estimates with draft settings and live deal changes', async () => {
        const feed = useWebSocketDataStore('openTrades')
        feed.setStatus('OPEN')
        feed.setRaw(JSON.stringify(draft.openTrades))
        const capital = { max_fund: 2500, reserve_safety_orders: true, budget_buffer_pct: 30 }
        const wrapper = mount(ConfigCapitalSection, { props: {
            capital, baseOrderSize: 12, maxSafetyOrders: 5,
            quoteCurrency: 'usdc', dynamicDcaEnabled: true, rules: {},
        } })
        expect(wrapper.text()).toContain('1,800.00 USDC')
        expect(wrapper.text()).toContain('93.60 USDC')

        await wrapper.setProps({ baseOrderSize: 20, maxSafetyOrders: 3 })
        expect(wrapper.text()).toContain('1,800.00 USDC')
        expect(wrapper.text()).toContain('104.00 USDC')
        feed.setRaw(JSON.stringify([{ so_count: 2 }]))
        await nextTick()
        expect(wrapper.text()).toContain('20.00 USDC')
        expect(wrapper.text()).toContain('1 open deal:')

        await wrapper.setProps({ capital: { ...capital, reserve_safety_orders: false } })
        expect(wrapper.text()).toContain('0.00 USDC (disabled)')
        expect(wrapper.text()).toContain('26.00 USDC')
    })

    it('shows unavailable data after disconnect instead of a stale reserve', async () => {
        const feed = useWebSocketDataStore('openTrades')
        feed.setStatus('OPEN')
        feed.setRaw(JSON.stringify(draft.openTrades))
        const wrapper = mount(ConfigCapitalSection, { props: {
            capital: { max_fund: 2500, reserve_safety_orders: true, budget_buffer_pct: 30 },
            baseOrderSize: 12, maxSafetyOrders: 5,
            quoteCurrency: 'usdc', dynamicDcaEnabled: true, rules: {},
        } })
        feed.setStatus('CLOSED')
        await nextTick()
        expect(wrapper.text()).toContain('Connect to the live trade feed')
        expect(wrapper.text()).not.toContain('1,800.00 USDC')
        expect(wrapper.text()).toContain('93.60 USDC')
    })
})
