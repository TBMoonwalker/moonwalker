import { onBeforeUnmount, onMounted, ref } from 'vue'

import { fetchJson } from '../api/client'
import type { AutopilotMemoryPayload } from '../autopilot/types'
import { extractApiErrorMessage } from '../helpers/apiErrors'

interface UseAutopilotMemoryFeedOptions {
    refreshIntervalMs?: number
}

export function useAutopilotMemoryFeed(
    options: UseAutopilotMemoryFeedOptions = {},
) {
    const data = ref<AutopilotMemoryPayload | null>(null)
    const error = ref<string | null>(null)
    const loading = ref(true)
    let intervalHandle: number | null = null
    const refreshIntervalMs = options.refreshIntervalMs ?? 15_000

    async function refresh(): Promise<void> {
        try {
            data.value = await fetchJson<AutopilotMemoryPayload>(
                '/autopilot/memory',
            )
            error.value = null
        } catch (err) {
            error.value = extractApiErrorMessage(
                err,
                'Autopilot memory could not be loaded.',
            )
        } finally {
            loading.value = false
        }
    }

    onMounted(() => {
        void refresh()
        if (typeof window !== 'undefined') {
            intervalHandle = window.setInterval(() => {
                void refresh()
            }, refreshIntervalMs)
        }
    })

    onBeforeUnmount(() => {
        if (intervalHandle !== null && typeof window !== 'undefined') {
            window.clearInterval(intervalHandle)
            intervalHandle = null
        }
    })

    return {
        data,
        error,
        loading,
        refresh,
    }
}
