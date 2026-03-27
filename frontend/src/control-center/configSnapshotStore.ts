import { computed, ref, shallowRef } from 'vue'

import { fetchJson } from '../api/client'
import { trackUiEvent } from '../utils/uiTelemetry'
import type {
    ConfigFreshnessPayload,
    ControlCenterConfigChangeOrigin,
    SharedConfigPayload,
} from './types'

type SnapshotLoadState = 'idle' | 'loading' | 'ready' | 'error'
type FreshnessStatus = 'unchanged' | 'stale' | 'unknown'
type LocalConfigChangeOrigin = Exclude<
    ControlCenterConfigChangeOrigin,
    'external_invalidation'
>

interface ConfigInvalidationEvent {
    at: number
    id: string
    origin: LocalConfigChangeOrigin
    senderId: string
    updatedAt: string | null
}

const CONFIG_INVALIDATION_CHANNEL = 'moonwalker.controlCenter.configInvalidation'
const CONFIG_INVALIDATION_STORAGE_KEY =
    'moonwalker.controlCenter.configInvalidation'
const LOCAL_CONFIG_CHANGE_ORIGINS = [
    'save',
    'restore',
    'live_activation',
] as const

const snapshot = shallowRef<SharedConfigPayload | null>(null)
const loadState = ref<SnapshotLoadState>('idle')
const loadError = ref<string | null>(null)
const latestKnownUpdatedAt = ref<string | null>(null)
const snapshotUpdatedAt = ref<string | null>(null)
const lastExternalInvalidationAt = ref<number | null>(null)
const lastExternalInvalidationOrigin = ref<LocalConfigChangeOrigin | null>(null)
const lastExternalInvalidationUpdatedAt = ref<string | null>(null)
const externalInvalidationToken = ref(0)
const isHydrated = computed(() => snapshot.value !== null)
const hasKnownNewerSnapshot = computed(
    () =>
        compareTimestamps(
            latestKnownUpdatedAt.value,
            snapshotUpdatedAt.value,
        ) > 0,
)

let pendingLoad: Promise<SharedConfigPayload | null> | null = null
let invalidationListenersInitialized = false
let invalidationChannel: BroadcastChannel | null = null
let storageEventHandler: ((event: StorageEvent) => void) | null = null
const invalidationSenderId = Math.random().toString(36).slice(2)
const processedInvalidationIds = new Set<string>()

function toTimestamp(value: string | null): number | null {
    if (!value) {
        return null
    }
    const parsed = Date.parse(value)
    return Number.isFinite(parsed) ? parsed : null
}

function compareTimestamps(a: string | null, b: string | null): number {
    const left = toTimestamp(a)
    const right = toTimestamp(b)
    if (left === null && right === null) {
        return 0
    }
    if (left === null) {
        return -1
    }
    if (right === null) {
        return 1
    }
    if (left === right) {
        return 0
    }
    return left > right ? 1 : -1
}

function rememberProcessedInvalidationId(id: string): void {
    processedInvalidationIds.add(id)
    if (processedInvalidationIds.size <= 16) {
        return
    }
    const oldestId = processedInvalidationIds.values().next().value
    if (oldestId) {
        processedInvalidationIds.delete(oldestId)
    }
}

function setLatestKnownUpdatedAt(updatedAt: string | null): string | null {
    if (
        updatedAt &&
        compareTimestamps(updatedAt, latestKnownUpdatedAt.value) > 0
    ) {
        latestKnownUpdatedAt.value = updatedAt
    }
    return latestKnownUpdatedAt.value
}

function setSnapshotState(
    nextSnapshot: SharedConfigPayload,
    updatedAt: string | null,
): void {
    const resolvedUpdatedAt = updatedAt ?? latestKnownUpdatedAt.value
    snapshot.value = nextSnapshot
    snapshotUpdatedAt.value = resolvedUpdatedAt
    setLatestKnownUpdatedAt(resolvedUpdatedAt)
    loadError.value = null
    loadState.value = 'ready'
}

function isLocalConfigChangeOrigin(
    value: unknown,
): value is LocalConfigChangeOrigin {
    return (
        typeof value === 'string' &&
        (LOCAL_CONFIG_CHANGE_ORIGINS as readonly string[]).includes(value)
    )
}

function parseInvalidationEvent(value: unknown): ConfigInvalidationEvent | null {
    if (!value || typeof value !== 'object') {
        return null
    }

    const candidate = value as Partial<ConfigInvalidationEvent>
    if (
        typeof candidate.id !== 'string' ||
        typeof candidate.senderId !== 'string' ||
        typeof candidate.at !== 'number' ||
        !isLocalConfigChangeOrigin(candidate.origin)
    ) {
        return null
    }

    return {
        at: candidate.at,
        id: candidate.id,
        origin: candidate.origin,
        senderId: candidate.senderId,
        updatedAt:
            candidate.updatedAt === null || typeof candidate.updatedAt === 'string'
                ? candidate.updatedAt
                : null,
    }
}

function applyExternalInvalidation(value: unknown): void {
    const event = parseInvalidationEvent(value)
    if (!event || event.senderId === invalidationSenderId) {
        return
    }
    if (processedInvalidationIds.has(event.id)) {
        return
    }

    rememberProcessedInvalidationId(event.id)
    setLatestKnownUpdatedAt(event.updatedAt)
    lastExternalInvalidationAt.value = event.at
    lastExternalInvalidationOrigin.value = event.origin
    lastExternalInvalidationUpdatedAt.value = event.updatedAt
    externalInvalidationToken.value += 1
}

function ensureInvalidationListeners(): void {
    if (invalidationListenersInitialized || typeof window === 'undefined') {
        return
    }

    invalidationListenersInitialized = true

    if (typeof BroadcastChannel !== 'undefined') {
        try {
            invalidationChannel = new BroadcastChannel(CONFIG_INVALIDATION_CHANNEL)
            invalidationChannel.onmessage = (event) => {
                applyExternalInvalidation(event.data)
            }
        } catch {
            invalidationChannel = null
        }
    }

    storageEventHandler = (event: StorageEvent) => {
        if (event.key !== CONFIG_INVALIDATION_STORAGE_KEY || !event.newValue) {
            return
        }
        try {
            applyExternalInvalidation(JSON.parse(event.newValue) as unknown)
        } catch {
            return
        }
    }

    window.addEventListener('storage', storageEventHandler)
}

async function refreshFreshnessMarker(): Promise<string | null> {
    try {
        const freshness = await fetchJson<ConfigFreshnessPayload>('/config/freshness')
        return setLatestKnownUpdatedAt(freshness.updated_at)
    } catch {
        return latestKnownUpdatedAt.value
    }
}

async function loadSnapshot(force = false): Promise<SharedConfigPayload | null> {
    if (pendingLoad) {
        return pendingLoad
    }
    pendingLoad = (async () => {
        loadState.value = 'loading'
        loadError.value = null
        try {
            const nextSnapshot = await fetchJson<SharedConfigPayload>('/config/all')
            const updatedAt = await refreshFreshnessMarker()
            setSnapshotState(nextSnapshot, updatedAt)
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
        const updatedAt = setLatestKnownUpdatedAt(freshness.updated_at)
        const isStale = compareTimestamps(updatedAt, snapshotUpdatedAt.value) > 0
        if (isStale) {
            trackUiEvent('control_center_snapshot_stale')
            return {
                status: 'stale',
                updatedAt,
            }
        }
        return {
            status: 'unchanged',
            updatedAt,
        }
    } catch {
        return {
            status: 'unknown',
            updatedAt: latestKnownUpdatedAt.value,
        }
    }
}

function applySnapshot(
    nextSnapshot: SharedConfigPayload,
    updatedAt: string | null = snapshotUpdatedAt.value ?? latestKnownUpdatedAt.value,
): void {
    setSnapshotState(nextSnapshot, updatedAt)
}

function emitLocalInvalidation(origin: LocalConfigChangeOrigin): void {
    ensureInvalidationListeners()

    const event: ConfigInvalidationEvent = {
        at: Date.now(),
        id: `${invalidationSenderId}-${Date.now()}-${Math.random().toString(36).slice(2)}`,
        origin,
        senderId: invalidationSenderId,
        updatedAt: latestKnownUpdatedAt.value ?? snapshotUpdatedAt.value,
    }

    rememberProcessedInvalidationId(event.id)

    if (invalidationChannel) {
        try {
            invalidationChannel.postMessage(event)
            return
        } catch {
            invalidationChannel = null
        }
    }

    if (typeof window === 'undefined') {
        return
    }

    try {
        window.localStorage.setItem(
            CONFIG_INVALIDATION_STORAGE_KEY,
            JSON.stringify(event),
        )
        window.localStorage.removeItem(CONFIG_INVALIDATION_STORAGE_KEY)
    } catch {
        return
    }
}

export function resetSharedConfigSnapshotState(): void {
    snapshot.value = null
    loadState.value = 'idle'
    loadError.value = null
    latestKnownUpdatedAt.value = null
    snapshotUpdatedAt.value = null
    lastExternalInvalidationAt.value = null
    lastExternalInvalidationOrigin.value = null
    lastExternalInvalidationUpdatedAt.value = null
    externalInvalidationToken.value = 0
    pendingLoad = null
    processedInvalidationIds.clear()

    if (invalidationChannel) {
        invalidationChannel.close()
        invalidationChannel = null
    }
    if (storageEventHandler && typeof window !== 'undefined') {
        window.removeEventListener('storage', storageEventHandler)
    }
    storageEventHandler = null
    invalidationListenersInitialized = false
}

export function useSharedConfigSnapshot() {
    ensureInvalidationListeners()

    return {
        snapshot,
        loadState,
        loadError,
        snapshotUpdatedAt,
        latestKnownUpdatedAt,
        lastKnownUpdatedAt: latestKnownUpdatedAt,
        lastExternalInvalidationAt,
        lastExternalInvalidationOrigin,
        lastExternalInvalidationUpdatedAt,
        externalInvalidationToken,
        isHydrated,
        hasKnownNewerSnapshot,
        applySnapshot,
        checkFreshness,
        ensureLoaded: loadSnapshot,
        refresh: () => loadSnapshot(true),
        emitLocalInvalidation,
        refreshFreshnessMarker,
    }
}
