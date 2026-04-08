import { ref } from 'vue'

import type { ControlCenterTransitionIntent } from '../control-center/types'

type TimeoutHandle = ReturnType<typeof setTimeout>

interface UseControlCenterFeedbackOptions {
    announcementDelayMs?: number
    buildAnnouncement?: (message: string | null) => string
    cancel?: (handle: TimeoutHandle) => void
    schedule?: (callback: () => void, delayMs: number) => TimeoutHandle
    successClearDelayMs?: number
}

function defaultBuildAnnouncement(message: string | null): string {
    return message ? message.trim() : ''
}

function defaultCancel(handle: TimeoutHandle): void {
    window.clearTimeout(handle)
}

function defaultSchedule(
    callback: () => void,
    delayMs: number,
): TimeoutHandle {
    return window.setTimeout(callback, delayMs)
}

export function useControlCenterFeedback(
    options: UseControlCenterFeedbackOptions = {},
) {
    const announcementDelayMs = options.announcementDelayMs ?? 10
    const buildAnnouncement = options.buildAnnouncement ?? defaultBuildAnnouncement
    const cancel = options.cancel ?? defaultCancel
    const schedule = options.schedule ?? defaultSchedule
    const successClearDelayMs = options.successClearDelayMs ?? 8000

    const liveRegionMessage = ref('')
    const transitionIntent = ref<ControlCenterTransitionIntent | null>(null)

    let transitionTimeoutHandle: TimeoutHandle | null = null

    function clearTransitionTimeout(): void {
        if (transitionTimeoutHandle === null) {
            return
        }
        cancel(transitionTimeoutHandle)
        transitionTimeoutHandle = null
    }

    function announce(messageText: string | null): void {
        liveRegionMessage.value = ''
        const nextMessage = buildAnnouncement(messageText)
        if (!nextMessage) {
            return
        }
        schedule(() => {
            liveRegionMessage.value = nextMessage
        }, announcementDelayMs)
    }

    function setTransitionIntent(nextIntent: ControlCenterTransitionIntent): void {
        transitionIntent.value = nextIntent
        clearTransitionTimeout()
        if (nextIntent.status === 'success') {
            transitionTimeoutHandle = schedule(() => {
                transitionIntent.value = null
                transitionTimeoutHandle = null
            }, successClearDelayMs)
        }
    }

    function disposeFeedback(): void {
        clearTransitionTimeout()
    }

    return {
        announce,
        disposeFeedback,
        liveRegionMessage,
        setTransitionIntent,
        transitionIntent,
    }
}
