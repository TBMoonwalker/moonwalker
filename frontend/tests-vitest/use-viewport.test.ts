import { mount } from '@vue/test-utils'
import { defineComponent, nextTick } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'

import {
    VIEWPORT_BREAKPOINTS,
    VIEWPORT_COMMIT_DEBOUNCE_MS,
    useViewport,
} from '../src/composables/useViewport'

function setViewportWidth(width: number): void {
    Object.defineProperty(window, 'innerWidth', {
        configurable: true,
        value: width,
    })
}

function resizeTo(width: number): void {
    setViewportWidth(width)
    window.dispatchEvent(new Event('resize'))
}

function settleCommits(): Promise<void> {
    return new Promise((resolve) =>
        setTimeout(resolve, VIEWPORT_COMMIT_DEBOUNCE_MS + 60),
    )
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

    it('commits breakpoint booleans only after resizes settle', async () => {
        setViewportWidth(VIEWPORT_BREAKPOINTS.desktop + 40)
        const wrapper = mount(ViewportConsumer)
        await settleCommits()
        expect(wrapper.text()).toBe('1240:false:false')

        // A fast drag updates the raw width immediately, but the booleans
        // keep the last settled band until the resizes settle.
        resizeTo(VIEWPORT_BREAKPOINTS.mobile - 1)
        resizeTo(VIEWPORT_BREAKPOINTS.mobile - 2)
        await nextTick()
        expect(wrapper.text()).toBe('766:false:false')

        await settleCommits()
        expect(wrapper.text()).toBe('766:true:false')

        resizeTo(VIEWPORT_BREAKPOINTS.desktop)
        await nextTick()
        expect(wrapper.text()).toBe('1200:true:false')

        await settleCommits()
        expect(wrapper.text()).toBe('1200:false:false')
        wrapper.unmount()
    })

    it('does not re-commit while another consumer owns a pending drag', async () => {
        setViewportWidth(VIEWPORT_BREAKPOINTS.desktop + 40)
        const first = mount(ViewportConsumer)
        await settleCommits()
        expect(first.text()).toBe('1240:false:false')

        // A drag is in flight (commit pending) when a second consumer
        // mounts: it must observe the held band, not force a commit.
        resizeTo(640)
        const second = mount(ViewportConsumer)
        await nextTick()
        expect(second.text()).toBe('640:false:false')
        expect(first.text()).toBe('640:false:false')

        await settleCommits()
        expect(first.text()).toBe('640:true:false')
        expect(second.text()).toBe('640:true:false')

        second.unmount()
        first.unmount()
    })

    it('cancels a pending commit when the last consumer unmounts', async () => {
        setViewportWidth(VIEWPORT_BREAKPOINTS.desktop + 40)
        const wrapper = mount(ViewportConsumer)
        await settleCommits()
        expect(wrapper.text()).toBe('1240:false:false')

        resizeTo(640)
        wrapper.unmount()
        await settleCommits()
        expect(wrapper.vm.isMobile).toBe(false)
        expect(wrapper.vm.isTablet).toBe(false)
    })
})
