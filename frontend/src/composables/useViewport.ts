import { computed, onMounted, onUnmounted, ref } from 'vue'

export const VIEWPORT_BREAKPOINTS = Object.freeze({
    mobile: 768,
    desktop: 1200,
})

const SSR_VIEWPORT_WIDTH = VIEWPORT_BREAKPOINTS.desktop
const viewportWidth = ref(readViewportWidth())
const isMobile = computed(
    () => viewportWidth.value < VIEWPORT_BREAKPOINTS.mobile,
)
const isTablet = computed(
    () =>
        viewportWidth.value >= VIEWPORT_BREAKPOINTS.mobile &&
        viewportWidth.value < VIEWPORT_BREAKPOINTS.desktop,
)
let activeConsumers = 0
let resizeListenerAttached = false

function readViewportWidth(): number {
    return typeof window === 'undefined'
        ? SSR_VIEWPORT_WIDTH
        : window.innerWidth
}

function handleViewportResize(): void {
    viewportWidth.value = readViewportWidth()
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
    window.removeEventListener('resize', handleViewportResize)
    resizeListenerAttached = false
}

export function useViewport() {
    viewportWidth.value = readViewportWidth()
    onMounted(attachViewportListener)
    onUnmounted(detachViewportListener)

    return {
        viewportWidth,
        isMobile,
        isTablet,
    }
}
