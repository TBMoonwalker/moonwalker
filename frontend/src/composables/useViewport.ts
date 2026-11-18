import { computed, onMounted, onUnmounted, ref } from 'vue'

export const VIEWPORT_BREAKPOINTS = Object.freeze({
    mobile: 768,
    desktop: 1200,
})

/**
 * Milliseconds to wait after the last resize event before the breakpoint
 * booleans re-evaluate.
 *
 * The raw width updates on every resize, but the booleans commit only once
 * the resizes settle. Flipping them mid-drag changes the trade table's
 * column set, which forces a full table re-render on every breakpoint
 * crossing (visible as flicker and, in WebKit, a blank table until the
 * next resize). Committing once the window is static keeps the column set
 * stable during a drag and flips it exactly once afterwards.
 */
export const VIEWPORT_COMMIT_DEBOUNCE_MS = 120

const SSR_VIEWPORT_WIDTH = VIEWPORT_BREAKPOINTS.desktop
const viewportWidth = ref(readViewportWidth())
const committedViewportWidth = ref(viewportWidth.value)
const isMobile = computed(
    () => committedViewportWidth.value < VIEWPORT_BREAKPOINTS.mobile,
)
const isTablet = computed(
    () =>
        committedViewportWidth.value >= VIEWPORT_BREAKPOINTS.mobile &&
        committedViewportWidth.value < VIEWPORT_BREAKPOINTS.desktop,
)
let activeConsumers = 0
let resizeListenerAttached = false
let commitTimer: ReturnType<typeof setTimeout> | undefined

function readViewportWidth(): number {
    return typeof window === 'undefined'
        ? SSR_VIEWPORT_WIDTH
        : window.innerWidth
}

function commitViewportWidth(): void {
    committedViewportWidth.value = readViewportWidth()
    commitTimer = undefined
}

function handleViewportResize(): void {
    viewportWidth.value = readViewportWidth()
    if (commitTimer !== undefined) {
        clearTimeout(commitTimer)
    }
    commitTimer = setTimeout(commitViewportWidth, VIEWPORT_COMMIT_DEBOUNCE_MS)
}

function attachViewportListener(): void {
    activeConsumers += 1
    if (resizeListenerAttached || typeof window === 'undefined') return
    handleViewportResize()
    window.addEventListener('resize', handleViewportResize)
    resizeListenerAttached = true
}

function detachViewportListener(): void {
    activeConsumers = Math.max(0, activeConsumers - 1)
    if (
        activeConsumers > 0 ||
        !resizeListenerAttached ||
        typeof window === 'undefined'
    ) {
        return
    }
    if (commitTimer !== undefined) {
        clearTimeout(commitTimer)
        commitTimer = undefined
    }
    window.removeEventListener('resize', handleViewportResize)
    resizeListenerAttached = false
}

export function useViewport() {
    viewportWidth.value = readViewportWidth()
    if (commitTimer === undefined) {
        committedViewportWidth.value = readViewportWidth()
    }
    onMounted(attachViewportListener)
    onUnmounted(detachViewportListener)

    return {
        viewportWidth,
        isMobile,
        isTablet,
    }
}
