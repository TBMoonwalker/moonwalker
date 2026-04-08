import {
    getTaskPresentation,
    resolveTargetForConfigKey,
} from './taskRegistry'
import type { ControlCenterBlocker } from './types'

export function resolveControlCenterBlocker(
    key: string,
    description: string,
    title?: string,
): ControlCenterBlocker {
    const task = getTaskPresentation(resolveTargetForConfigKey(key))

    return {
        key,
        title: title?.trim() || task.title,
        description,
        mode: task.defaultMode,
        target: task.target,
    }
}

export function normalizeControlCenterBlockers(
    rawBlockers: unknown,
): ControlCenterBlocker[] {
    if (!Array.isArray(rawBlockers)) {
        return []
    }

    return rawBlockers
        .map((blocker) => {
            if (!blocker || typeof blocker !== 'object') {
                return null
            }

            const key = String((blocker as { key?: unknown }).key ?? '').trim()
            if (!key) {
                return null
            }

            const description = String(
                (blocker as { message?: unknown }).message ??
                    'Resolve this blocker before continuing.',
            ).trim()

            return resolveControlCenterBlocker(key, description)
        })
        .filter((blocker): blocker is ControlCenterBlocker => blocker !== null)
}
