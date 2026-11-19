import { mount } from '@vue/test-utils'
import { defineComponent, ref, watch, type Ref } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { usePinnedTableWidth } from '../src/composables/usePinnedTableWidth'
import { VIEWPORT_COMMIT_DEBOUNCE_MS } from '../src/composables/useViewport'

let observerCallback: ResizeObserverCallback | undefined
let observed: Element[] = []

class MockResizeObserver {
    observe(element: Element) {
        observed.push(element)
    }

    unobserve() {}

    disconnect() {
        observerCallback = undefined
    }

    constructor(callback: ResizeObserverCallback) {
        observerCallback = callback
    }
}

type PinnedApi = ReturnType<typeof usePinnedTableWidth>

function makePanel(width: number, padding = 16) {
    const panel = document.createElement('div')
    Object.defineProperty(panel, 'clientWidth', {
        value: width,
        configurable: true,
        writable: true,
    })
    vi.spyOn(window, 'getComputedStyle').mockReturnValue({
        paddingLeft: `${padding}px`,
        paddingRight: `${padding}px`,
    } as unknown as CSSStyleDeclaration)
    return panel
}

// clientWidth is read-only in the DOM lib; the stub above makes it writable.
function setPanelWidth(panel: HTMLElement, width: number) {
    Object.defineProperty(panel, 'clientWidth', {
        value: width,
        configurable: true,
        writable: true,
    })
}

function mountProbe(panel: HTMLElement | null) {
    const apiHolder: { api?: PinnedApi } = {}
    const host = defineComponent({
        setup() {
            const panelRef = ref<HTMLElement | null>(panel)
            apiHolder.api = usePinnedTableWidth(panelRef)
            return () => null
        },
    })
    const wrapper = mount(host)
    return { wrapper, api: apiHolder.api as PinnedApi }
}

beforeEach(() => {
    vi.useFakeTimers()
    observerCallback = undefined
    observed = []
    vi.stubGlobal('ResizeObserver', MockResizeObserver)
})

afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
})

describe('usePinnedTableWidth', () => {
    it('pins to the panel content width immediately on mount', () => {
        const panel = makePanel(800)
        const { api, wrapper } = mountProbe(panel)
        expect(api.committedWidth.value).toBe(768)
        expect(api.widthStyle.value).toEqual({ width: '768px' })
        expect(observed).toEqual([panel])
        wrapper.unmount()
    })

    it('ignores rapid resizes and commits once after the drag settles', async () => {
        const panel = makePanel(800)
        const { api, wrapper } = mountProbe(panel)
        let changes = 0
        watch(api.committedWidth, () => {
            changes += 1
        })

        // Simulate a drag: the panel width changes and the RO fires on
        // every frame before the debounce window has closed.
        setPanelWidth(panel, 740)
        for (let i = 0; i < 5; i += 1) {
            observerCallback?.([], undefined as unknown as ResizeObserver)
            await vi.advanceTimersByTimeAsync(40)
        }
        expect(changes).toBe(0)
        expect(api.committedWidth.value).toBe(768)

        // The last resize is followed by a quiet period: one commit.
        setPanelWidth(panel, 700)
        observerCallback?.([], undefined as unknown as ResizeObserver)
        await vi.advanceTimersByTimeAsync(VIEWPORT_COMMIT_DEBOUNCE_MS)
        expect(changes).toBe(1)
        expect(api.committedWidth.value).toBe(668)
        wrapper.unmount()
    })

    it('rounds the committed width to whole pixels', () => {
        const panel = makePanel(800, 16.5)
        const { api, wrapper } = mountProbe(panel)
        expect(api.committedWidth.value).toBe(767)
        wrapper.unmount()
    })

    it('stays unstyled when there is no panel to observe', () => {
        const { api, wrapper } = mountProbe(null)
        expect(api.committedWidth.value).toBeNull()
        expect(api.widthStyle.value).toBeUndefined()
        expect(observed).toEqual([])
        wrapper.unmount()
    })
})
