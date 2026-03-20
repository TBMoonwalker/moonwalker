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

export function buildLiveRegionAnnouncement(
    transition: ControlCenterTransitionIntent | null,
): string {
    if (!transition) {
        return ''
    }
    return transition.message.trim()
}
