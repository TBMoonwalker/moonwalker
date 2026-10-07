import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { describe, expect, it, beforeEach } from 'vitest'

import ConfigCapitalSection from '../src/components/config/ConfigCapitalSection.vue'
import type { CapitalModel } from '../src/config-editor/types'

const baseCapital: CapitalModel = {
    max_fund: 2_500,
    reserve_safety_orders: true,
    budget_buffer_pct: 30,
}

interface SectionProps {
    showBaseFields?: boolean
    showExpertFields?: boolean
    dynamicDcaEnabled?: boolean
    cardTitle?: string | null
}

function mountSection(props: SectionProps = {}) {
    return mount(ConfigCapitalSection, {
        props: {
            capital: { ...baseCapital },
            baseOrderSize: 12,
            maxSafetyOrders: 5,
            quoteCurrency: 'usdc',
            dynamicDcaEnabled: true,
            rules: {},
             ...props,
         },
      })
}

describe('ConfigCapitalSection control surface', () => {
    beforeEach(() => setActivePinia(createPinia()))

    it('renders a section title, falling back to the default label', () => {
        expect(mountSection({ cardTitle: 'My budget' }).text()).toContain('My budget')
        expect(mountSection().text()).toContain('Capital budget')
       })

    it('hides the global max fund control when base fields are turned off', () => {
        expect(mountSection({ showBaseFields: false }).text()).not.toContain('Global max fund')
        expect(mountSection({ showBaseFields: true }).text()).toContain('Global max fund')
       })

    it('gates both expert controls on showExpertFields', () => {
        const hidden = mountSection({ showExpertFields: false })
        expect(hidden.text()).not.toContain('Reserve safety-order budget')
        expect(hidden.text()).not.toContain('Budget buffer for dynamic safety orders')

        const shown = mountSection({ showExpertFields: true })
        expect(shown.text()).toContain('Reserve safety-order budget')
        expect(shown.text()).toContain('Budget buffer for dynamic safety orders')
       })

    it('gates the buffer control on dynamic DCA while keeping the reserve control', () => {
        const dcaOff = mountSection({ showExpertFields: true, dynamicDcaEnabled: false })
          // only the dynamic-DCA buffer line is gated; the reserve control stays
        expect(dcaOff.text()).not.toContain('Budget buffer for dynamic safety orders')
        expect(dcaOff.text()).toContain('Reserve safety-order budget')
       })

    it('exposes validate() that resolves true for a clean form', async () => {
        const wrapper = mountSection()
        const withApi = wrapper.vm as unknown as { validate: () => Promise<boolean> }
        expect(await withApi.validate()).toBe(true)
       })
})
