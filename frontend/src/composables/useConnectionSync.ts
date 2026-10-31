import { computed, type ComputedRef, type Ref } from 'vue'
import { storeToRefs } from 'pinia'

import { useWebSocketDataStore, type WebSocketStatus } from '../stores/websocket'

/**
 * The lifecycle phase of Moonwalker's realtime data feeds.
 *
 * `connected` is the healthy steady state: every authoritative feed is open and
 * serving fresh snapshots. The intermediate phases describe what the operator
 * should see in the top bar while the frontend is *waiting for data* — most
 * visibly after a browser tab has been re-activated and the socket is resuming
 * without discarding the last-known values.
 */
export type ConnectionPhase = 'connected' | 'connecting' | 'syncing' | 'reconnecting'

/** A plain, testable snapshot of a single realtime feed. */
export type SyncStreamView = {
    status: WebSocketStatus
    fresh: boolean
    hasReceivedData: boolean
    isRecovery: boolean
}

export type ConnectionState = {
    phase: ConnectionPhase
    connected: boolean
    label: string
}

const PHASE_LABELS: Record<ConnectionPhase, string> = {
    connected: 'Connected',
    connecting: 'Connecting…',
    syncing: 'Syncing…',
    reconnecting: 'Reconnecting…',
}

function isFeedReady(view: SyncStreamView): boolean {
    if (view.status !== 'OPEN') {
        return false
    }
    // Recovery feeds re-pull a full snapshot on resume, so their `fresh` flag is
    // the signal that data has caught up. Push-only feeds only expose
    // `hasReceivedData` and may legitimately stay empty, so `fresh` would read as
    // "not ready" for good reason.
    return view.isRecovery ? view.fresh : view.hasReceivedData
}

/**
 * Derive the overall connection phase from every realtime feed.
 *
 * Recovery feeds (open trades, statistics) are authoritative for `connected`;
 * supplementary feeds (closed/unsellable trades) only contribute the "a socket is
 * not open" signal, so a dropped socket still reads as *reconnecting* without
 * forcing a permanently non-connected state when those feeds are simply empty.
 *
 * @param streams - One snapshot per managed websocket.
 * @returns The phase, whether the app is fully connected, and a user-facing label.
 */
export function deriveConnectionState(
    streams: readonly SyncStreamView[],
): ConnectionState {
    if (streams.length === 0) {
        return { phase: 'connected', connected: true, label: PHASE_LABELS.connected }
    }

    const recovery = streams.filter((stream) => stream.isRecovery)
    // Recovery feeds are authoritative; fall back to all feeds if none are marked
    // recovery so the function still yields a usable phase on partial configs.
    const authoritative = recovery.length > 0 ? recovery : streams
    const allOpen = streams.every((stream) => stream.status === 'OPEN')
    const authoritativeReady = authoritative.every(isFeedReady)

    // Fully healthy: every socket is open and the authoritative feed is fresh.
    // Supplementary feeds may legitimately be empty, so only their *status*
    // (not their data) gates `connected`.
    if (allOpen && authoritativeReady) {
        return { phase: 'connected', connected: true, label: PHASE_LABELS.connected }
    }

    // At least one socket is down. Distinguish a first load (no authoritative
    // data yet) from an ongoing reconnect (we already had a snapshot).
    if (!allOpen) {
        const noDataYet = authoritative.some((stream) => !stream.hasReceivedData)
        const phase: ConnectionPhase = noDataYet ? 'connecting' : 'reconnecting'
        return { phase, connected: false, label: PHASE_LABELS[phase] }
    }

    // Every socket is open, but the authoritative feed has not produced a fresh
    // snapshot yet: the frontend is mid-refresh.
    return { phase: 'syncing', connected: false, label: PHASE_LABELS.syncing }
}

type SyncStreamRefs = {
    status: Ref<WebSocketStatus>
    fresh: Ref<boolean>
    hasReceivedData: Ref<boolean>
    isRecovery: boolean
}

// openTrades and statistics are "recovery" sockets: they re-pull a full snapshot
// on resume, so `fresh` marks "data has caught up". closed/unsellable trades are
// push-only and may stay empty, so they are supplementary for the connected state.
const STREAM_SPECS = [
    { id: 'openTrades', isRecovery: true },
    { id: 'statistics', isRecovery: true },
    { id: 'closedTrades', isRecovery: false },
    { id: 'unsellableTrades', isRecovery: false },
] as const

/**
 * Reactively derive the global connection phase from every managed websocket
 * store. UI layers drive a sync bar and status badge from the returned computed
 * so the operator can tell the frontend is waiting for data after a tab
 * re-activation instead of seeing a frozen, misleadingly-stable screen.
 */
export function useConnectionSync(): {
    connection: ComputedRef<ConnectionState>
} {
    const refs: SyncStreamRefs[] = STREAM_SPECS.map((spec): SyncStreamRefs => {
        const store = useWebSocketDataStore(spec.id)
        const { status, fresh, hasReceivedData } = storeToRefs(store)
        return { status, fresh, hasReceivedData, isRecovery: spec.isRecovery }
    })

    const connection = computed<ConnectionState>(() =>
        deriveConnectionState(
            refs.map((stream) => ({
                status: stream.status.value,
                fresh: stream.fresh.value,
                hasReceivedData: stream.hasReceivedData.value,
                isRecovery: stream.isRecovery,
            })),
        ),
    )

    return { connection }
}
