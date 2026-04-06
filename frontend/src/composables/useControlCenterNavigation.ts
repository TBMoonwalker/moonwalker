import type { ComputedRef } from 'vue'

import {
    deriveGuidedFocusTarget,
    waitForTargetElement,
} from '../control-center/focusFlow'
import {
    buildControlCenterQuery,
    normalizeControlCenterRouteState,
} from '../control-center/routeState'
import { getTaskPresentation } from '../control-center/taskRegistry'
import type {
    ControlCenterMode,
    ControlCenterRouteState,
    ControlCenterTarget,
} from '../control-center/types'
import { trackUiEvent } from '../utils/uiTelemetry'

type UiTelemetryPayload = Record<string, string | number | boolean | null>

interface RouterLocationLike {
    name: string
    query: Record<string, string>
}

interface RouterLike {
    push: (location: RouterLocationLike) => Promise<unknown>
    replace: (location: RouterLocationLike) => Promise<unknown>
}

interface WaitForTargetElementOptions {
    nextTick: () => Promise<void>
    read: () => HTMLElement | null
}

interface UseControlCenterNavigationOptions {
    announce: (message: string | null) => void
    nextTick: () => Promise<void>
    readTargetElement: (target: ControlCenterTarget) => HTMLElement | null
    routeState: ComputedRef<ControlCenterRouteState>
    router: RouterLike
    trackEvent?: (eventName: string, payload?: UiTelemetryPayload) => void
    waitForTarget?: (
        options: WaitForTargetElementOptions,
    ) => Promise<HTMLElement | null>
}

function defaultTrackEvent(
    eventName: string,
    payload?: UiTelemetryPayload,
): void {
    trackUiEvent(eventName, payload)
}

export function useControlCenterNavigation(
    options: UseControlCenterNavigationOptions,
) {
    const trackEvent = options.trackEvent ?? defaultTrackEvent
    const waitForTarget = options.waitForTarget ?? waitForTargetElement

    async function navigateToControlCenter(
        mode: ControlCenterMode,
        target: ControlCenterTarget | null = null,
        replace = false,
    ): Promise<void> {
        const normalizedState = normalizeControlCenterRouteState({
            requestedMode: mode,
            requestedTarget: target,
            fallbackMode: mode,
        })
        const location = {
            name: 'controlCenter',
            query: buildControlCenterQuery(normalizedState),
        }
        if (replace) {
            await options.router.replace(location)
            return
        }
        await options.router.push(location)
    }

    async function focusTarget(target: ControlCenterTarget): Promise<boolean> {
        const element = await waitForTarget({
            nextTick: options.nextTick,
            read: () => options.readTargetElement(target),
        })
        if (!element) {
            return false
        }
        element.scrollIntoView({
            behavior: 'auto',
            block: 'start',
        })
        const focusAnchor =
            element.querySelector<HTMLElement>('[data-control-center-anchor]') ??
            element
        focusAnchor.focus({ preventScroll: true })
        options.announce(deriveGuidedFocusTarget(target).announcement)
        return true
    }

    async function guideToTarget(target: ControlCenterTarget): Promise<void> {
        const task = getTaskPresentation(target)
        const requiresRouteTransition =
            options.routeState.value.mode !== task.defaultMode ||
            options.routeState.value.target !== target
        trackEvent('control_center_fix_this_requested', {
            target,
            mode: task.defaultMode,
        })
        await navigateToControlCenter(task.defaultMode, target)
        if (!requiresRouteTransition) {
            await focusTarget(target)
        }
    }

    async function handleModeSelect(mode: ControlCenterMode): Promise<void> {
        const currentTarget = options.routeState.value.target
        const nextTarget =
            currentTarget &&
            getTaskPresentation(currentTarget).modes.includes(mode)
                ? currentTarget
                : null
        await navigateToControlCenter(mode, nextTarget)
    }

    return {
        focusTarget,
        guideToTarget,
        handleModeSelect,
        navigateToControlCenter,
    }
}
