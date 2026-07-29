import { mount } from '@vue/test-utils'
import { defineComponent, nextTick } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'

import {
    VIEWPORT_BREAKPOINTS,
    useViewport,
} from '../src/composables/useViewport'

function setViewportWidth(width: number): void {
    Object.defineProperty(window, 'innerWidth', {
        configurable: true,
        value: width,
    })
}

const ViewportConsumer = defineComponent({
    setup() {
        return useViewport()
    },
    template: '<span>{{ viewportWidth }}:{{ isMobile }}:{{ isTablet }}</span>',
})

afterEach(() => {
    vi.restoreAllMocks()
    setViewportWidth(VIEWPORT_BREAKPOINTS.desktop)
})

describe('useViewport', () => {
    it('shares one resize listener across active consumers', () => {
        const addListener = vi.spyOn(window, 'addEventListener')
        const removeListener = vi.spyOn(window, 'removeEventListener')
        const wrapper = mount(
            defineComponent({
                components: { ViewportConsumer },
                template:
                    '<ViewportConsumer /><ViewportConsumer /><ViewportConsumer />',
            }),
        )

        expect(
            addListener.mock.calls.filter(([event]) => event === 'resize'),
        ).toHaveLength(1)

        wrapper.unmount()

        expect(
            removeListener.mock.calls.filter(([event]) => event === 'resize'),
        ).toHaveLength(1)
    })

    it('exposes canonical mobile and tablet breakpoints reactively', async () => {
        setViewportWidth(VIEWPORT_BREAKPOINTS.mobile - 1)
        const wrapper = mount(ViewportConsumer)
        expect(wrapper.text()).toBe('767:true:false')

        setViewportWidth(VIEWPORT_BREAKPOINTS.mobile)
        window.dispatchEvent(new Event('resize'))
        await nextTick()
        expect(wrapper.text()).toBe('768:false:true')

        setViewportWidth(VIEWPORT_BREAKPOINTS.desktop)
        window.dispatchEvent(new Event('resize'))
        await nextTick()
        expect(wrapper.text()).toBe('1200:false:false')
    })
})
