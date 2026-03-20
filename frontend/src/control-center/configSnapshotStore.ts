import { computed, ref, shallowRef } from 'vue'

import { fetchJson } from '../api/client'
import { trackUiEvent } from '../utils/uiTelemetry'
import type { ConfigFreshnessPayload, SharedConfigPayload } from './types'

type SnapshotLoadState = 'idle' | 'loading' | 'ready' | 'error'
type FreshnessStatus = 'unchanged' | 'stale' | 'unknown'

const snapshot = shallowRef<SharedConfigPayload | null>(null)
const loadState = ref<SnapshotLoadState>('idle')
const loadError = ref<string | null>(null)
const lastKnownUpdatedAt = ref<string | null>(null)
const isHydrated = computed(() => snapshot.value !== null)

let pendingLoad: Promise<SharedConfigPayload | null> | null = null

function toTimestamp(value: string | null): number | null {
    if (!value) {
        return null
    }
    const parsed = Date.parse(value)
    return Number.isFinite(parsed) ? parsed : null
}

async function refreshFreshnessMarker(): Promise<string | null> {
    try {
        const freshness = await fetchJson<ConfigFreshnessPayload>('/config/freshness')
        lastKnownUpdatedAt.value = freshness.updated_at
        return freshness.updated_at
    } catch {
        return lastKnownUpdatedAt.value
    }
}

async function loadSnapshot(force = false): Promise<SharedConfigPayload | null> {
    if (pendingLoad && !force) {
        return pendingLoad
    }
    pendingLoad = (async () => {
        loadState.value = 'loading'
        loadError.value = null
        try {
            const nextSnapshot = await fetchJson<SharedConfigPayload>('/config/all')
            snapshot.value = nextSnapshot
            await refreshFreshnessMarker()
            loadState.value = 'ready'
            trackUiEvent('control_center_snapshot_loaded')
            return nextSnapshot
        } catch (error) {
            loadState.value = 'error'
            loadError.value =
                error instanceof Error
                    ? error.message
                    : 'Failed to load configuration.'
            trackUiEvent('control_center_snapshot_failed')
            throw error
        } finally {
            pendingLoad = null
        }
    })()

    return pendingLoad
}

async function checkFreshness(): Promise<{
    status: FreshnessStatus
    updatedAt: string | null
}> {
    try {
        const freshness = await fetchJson<ConfigFreshnessPayload>('/config/freshness')
        const currentTimestamp = toTimestamp(lastKnownUpdatedAt.value)
        const incomingTimestamp = toTimestamp(freshness.updated_at)
        const isStale =
            currentTimestamp !== null &&
            incomingTimestamp !== null &&
            incomingTimestamp > currentTimestamp
        if (freshness.updated_at) {
            lastKnownUpdatedAt.value = freshness.updated_at
        }
        if (isStale) {
            trackUiEvent('control_center_snapshot_stale')
            return {
                status: 'stale',
                updatedAt: freshness.updated_at,
            }
        }
        return {
            status: 'unchanged',
            updatedAt: freshness.updated_at,
        }
    } catch {
        return {
            status: 'unknown',
            updatedAt: lastKnownUpdatedAt.value,
        }
    }
}

function applySnapshot(
    nextSnapshot: SharedConfigPayload,
    updatedAt: string | null = lastKnownUpdatedAt.value,
): void {
    snapshot.value = nextSnapshot
    lastKnownUpdatedAt.value = updatedAt
    loadError.value = null
    loadState.value = 'ready'
}

export function resetSharedConfigSnapshotState(): void {
    snapshot.value = null
    loadState.value = 'idle'
    loadError.value = null
    lastKnownUpdatedAt.value = null
    pendingLoad = null
}

export function useSharedConfigSnapshot() {
    return {
        snapshot,
        loadState,
        loadError,
        lastKnownUpdatedAt,
        isHydrated,
        applySnapshot,
        checkFreshness,
        ensureLoaded: loadSnapshot,
        refresh: () => loadSnapshot(true),
        refreshFreshnessMarker,
    }
}
