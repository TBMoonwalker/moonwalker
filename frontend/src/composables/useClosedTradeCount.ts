import { ref, watch, type Ref } from 'vue'

import { fetchJson } from '../api/client'

export function useClosedTradeCount(livePage: Ref<unknown>): Ref<number | null> {
    const count = ref<number | null>(null)

    watch(
        livePage,
        async (_page, _previousPage, onCleanup) => {
            let cancelled = false
            onCleanup(() => {
                cancelled = true
            })

            try {
                const response = await fetchJson<{ result: number }>(
                    '/trades/closed/length',
                )
                if (!cancelled) {
                    count.value = Number.isSafeInteger(response.result) && response.result >= 0
                        ? response.result
                        : null
                }
            } catch {
                if (!cancelled) count.value = null
            }
        },
        { immediate: true },
    )

    return count
}
