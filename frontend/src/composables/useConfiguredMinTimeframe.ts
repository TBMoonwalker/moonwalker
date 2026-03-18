import { ref } from 'vue'

import { fetchJson } from '../api/client'
import {
    DEFAULT_MIN_TIMEFRAME,
    resolveMinTimeframe,
    type OpenTradesConfigResponse,
    type TimeframeChoice,
} from '../helpers/openTrades'

export function useConfiguredMinTimeframe() {
    const configuredMinTimeframe = ref<TimeframeChoice>(DEFAULT_MIN_TIMEFRAME)

    async function loadConfiguredMinTimeframe(): Promise<void> {
        try {
            const config = await fetchJson<OpenTradesConfigResponse>(
                '/config/all',
            )
            configuredMinTimeframe.value = resolveMinTimeframe(
                config.timeframe,
            )
        } catch (_error) {
            configuredMinTimeframe.value = resolveMinTimeframe(null)
        }
    }

    return {
        configuredMinTimeframe,
        loadConfiguredMinTimeframe,
    }
}
