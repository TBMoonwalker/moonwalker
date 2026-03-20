import { ref } from 'vue'

import { useSharedConfigSnapshot } from '../control-center/configSnapshotStore'
import {
    DEFAULT_MIN_TIMEFRAME,
    resolveMinTimeframe,
    type TimeframeChoice,
} from '../helpers/openTrades'

export function useConfiguredMinTimeframe() {
    const configuredMinTimeframe = ref<TimeframeChoice>(DEFAULT_MIN_TIMEFRAME)
    const configSnapshotStore = useSharedConfigSnapshot()

    async function loadConfiguredMinTimeframe(): Promise<void> {
        try {
            const config =
                (await configSnapshotStore.ensureLoaded(false)) ??
                configSnapshotStore.snapshot.value
            configuredMinTimeframe.value = resolveMinTimeframe(
                config?.timeframe ?? null,
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
