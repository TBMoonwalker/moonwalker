import { getTaskPresentation } from './taskRegistry'
import type {
    ControlCenterTarget,
    ControlCenterTransitionIntent,
} from './types'

export function deriveGuidedFocusTarget(target: ControlCenterTarget): {
    announcement: string
    sectionId: string
    title: string
} {
    const task = getTaskPresentation(target)
    return {
        announcement: `${task.title} opened.`,
        sectionId: task.sectionId,
        title: task.title,
    }
}

interface WaitForTargetElementOptions<TElement> {
    attempts?: number
    nextTick?: () => Promise<void>
    read: () => TElement | null
    requestAnimationFrame?: (callback: FrameRequestCallback) => number
}

const DEFAULT_TARGET_ELEMENT_ATTEMPTS = 24

export async function waitForTargetElement<TElement>(
    options: WaitForTargetElementOptions<TElement>,
): Promise<TElement | null> {
    const attempts = Math.max(
        1,
        options.attempts ?? DEFAULT_TARGET_ELEMENT_ATTEMPTS,
    )
    const flushDom = options.nextTick ?? (async () => {})
    const scheduleFrame =
        options.requestAnimationFrame ??
        ((callback: FrameRequestCallback) => {
            if (
                typeof window !== 'undefined' &&
                typeof window.requestAnimationFrame === 'function'
            ) {
                return window.requestAnimationFrame(callback)
            }
            return window.setTimeout(() => callback(0), 0)
        })

    for (let attempt = 0; attempt < attempts; attempt += 1) {
        await flushDom()
        const element = options.read()
        if (element) {
            return element
        }
        if (attempt === attempts - 1) {
            break
        }
        await new Promise<void>((resolve) => {
            scheduleFrame(() => resolve())
        })
    }

    return null
}

export function buildLiveRegionAnnouncement(
    transition: ControlCenterTransitionIntent | null,
): string {
    if (!transition) {
        return ''
    }
    return transition.message.trim()
}
