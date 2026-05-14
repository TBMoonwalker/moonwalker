import { computed, onMounted, onUnmounted } from 'vue'

import { useSharedConfigSnapshot } from '../control-center/configSnapshotStore'

const TRADING_PAUSE_REFRESH_INTERVAL_MS = 15000

export function useTradingPauseStatus() {
    const snapshotStore = useSharedConfigSnapshot()
    const tradingPaused = computed(
        () => Boolean(snapshotStore.snapshot.value?.trading_paused),
    )

    let refreshIntervalId: number | null = null

    async function refreshTradingPauseStatus(force = false): Promise<void> {
        if (!snapshotStore.snapshot.value || force) {
            await snapshotStore.ensureLoaded(force)
            return
        }

        const freshness = await snapshotStore.checkFreshness()
        if (freshness.status === 'stale') {
            await snapshotStore.refresh()
        }
    }

    onMounted(() => {
        void refreshTradingPauseStatus(false)
        if (typeof window !== 'undefined') {
            refreshIntervalId = window.setInterval(() => {
                void refreshTradingPauseStatus(false)
            }, TRADING_PAUSE_REFRESH_INTERVAL_MS)
        }
    })

    onUnmounted(() => {
        if (refreshIntervalId !== null && typeof window !== 'undefined') {
            window.clearInterval(refreshIntervalId)
        }
    })

    return {
        refreshTradingPauseStatus,
        tradingPaused,
    }
}
