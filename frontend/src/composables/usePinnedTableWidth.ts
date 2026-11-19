import { computed, onMounted, onUnmounted, ref, type Ref } from 'vue'

import { VIEWPORT_COMMIT_DEBOUNCE_MS } from './useViewport'

/**
 * Pin a fluid-width child to the panel's last committed content width.
 *
 * The panel itself stays fluid and tracks the window on every resize, but the
 * pinned child (the trade table) only re-lays out once the resizes settle.
 * During a continuous drag the child's width never changes, so the browser
 * performs no table reflow, no layer re-rasterization and (because naive-ui's
 * table ResizeObserver watches the table) no table re-render per frame.
 * Without this, each drag frame re-lays out and re-paints the full table,
 * which WebKit (Safari) shows as a white flash of the table region on every
 * frame of the drag.
 *
 * The committed width is the panel's content box (clientWidth minus
 * horizontal padding), rounded to whole pixels so sub-pixel window movement
 * does not churn the style.
 */
export function usePinnedTableWidth(panelRef: Ref<HTMLElement | null>) {
    const committedWidth = ref<number | null>(null)
    let observer: ResizeObserver | undefined
    let commitTimer: ReturnType<typeof setTimeout> | undefined

    function readPanelContentWidth(): number | null {
        const panel = panelRef.value
        if (!panel) {
            return null
        }
        const style = window.getComputedStyle(panel)
        const paddingLeft = parseFloat(style.paddingLeft) || 0
        const paddingRight = parseFloat(style.paddingRight) || 0
        return Math.max(
            0,
            Math.round(panel.clientWidth - paddingLeft - paddingRight),
        )
    }

    function commit(): void {
        committedWidth.value = readPanelContentWidth()
        commitTimer = undefined
    }

    function handlePanelResize(): void {
        if (commitTimer !== undefined) {
            clearTimeout(commitTimer)
        }
        commitTimer = setTimeout(commit, VIEWPORT_COMMIT_DEBOUNCE_MS)
    }

    onMounted(() => {
        commit()
        if (typeof ResizeObserver === 'undefined') {
            return
        }
        const panel = panelRef.value
        if (!panel) {
            return
        }
        observer = new ResizeObserver(() => {
            handlePanelResize()
        })
        observer.observe(panel)
    })

    onUnmounted(() => {
        if (observer) {
            observer.disconnect()
        }
        if (commitTimer !== undefined) {
            clearTimeout(commitTimer)
            commitTimer = undefined
        }
    })

    return {
        committedWidth,
        widthStyle: computed(() =>
            committedWidth.value === null
                ? undefined
                : { width: `${committedWidth.value}px` },
        ),
    }
}
