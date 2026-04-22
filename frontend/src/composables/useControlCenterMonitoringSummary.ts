import { computed } from 'vue'
import { storeToRefs } from 'pinia'

import { useWebSocketDataStore } from '../stores/websocket'
import type { WebSocketStatus } from '../stores/websocket'

export interface ControlCenterMonitoringStreamSummary {
    key: string
    label: string
    status: WebSocketStatus
    hasReceivedData: boolean
    reconnectCount: number
}

export type ControlCenterMonitoringHealth =
    | 'healthy'
    | 'warming_up'
    | 'reconnecting'
    | 'attention_needed'

export function useControlCenterMonitoringSummary() {
    const openTradesStore = useWebSocketDataStore('openTrades')
    const closedTradesStore = useWebSocketDataStore('closedTrades')
    const unsellableTradesStore = useWebSocketDataStore('unsellableTrades')
    const statisticsStore = useWebSocketDataStore('statistics')

    const openTradesState = storeToRefs(openTradesStore)
    const closedTradesState = storeToRefs(closedTradesStore)
    const unsellableTradesState = storeToRefs(unsellableTradesStore)
    const statisticsState = storeToRefs(statisticsStore)

    const streams = computed<ControlCenterMonitoringStreamSummary[]>(() => [
        {
            key: 'open',
            label: 'Open trades',
            status: openTradesState.status.value,
            hasReceivedData: openTradesState.hasReceivedData.value,
            reconnectCount: openTradesState.reconnectCount.value,
        },
        {
            key: 'closed',
            label: 'Closed trades',
            status: closedTradesState.status.value,
            hasReceivedData: closedTradesState.hasReceivedData.value,
            reconnectCount: closedTradesState.reconnectCount.value,
        },
        {
            key: 'unsellable',
            label: 'Unsellable trades',
            status: unsellableTradesState.status.value,
            hasReceivedData: unsellableTradesState.hasReceivedData.value,
            reconnectCount: unsellableTradesState.reconnectCount.value,
        },
        {
            key: 'statistics',
            label: 'Statistics',
            status: statisticsState.status.value,
            hasReceivedData: statisticsState.hasReceivedData.value,
            reconnectCount: statisticsState.reconnectCount.value,
        },
    ])

    const totalStreams = computed(() => streams.value.length)
    const openCount = computed(
        () => streams.value.filter((stream) => stream.status === 'OPEN').length,
    )
    const receivingCount = computed(
        () =>
            streams.value.filter(
                (stream) => stream.status === 'OPEN' && stream.hasReceivedData,
            ).length,
    )
    const totalReconnects = computed(() =>
        streams.value.reduce(
            (total, stream) => total + stream.reconnectCount,
            0,
        ),
    )

    const closedStream = computed(
        () => streams.value.find((stream) => stream.status === 'CLOSED') ?? null,
    )
    const connectingStream = computed(
        () =>
            streams.value.find((stream) => stream.status === 'CONNECTING') ??
            null,
    )
    const waitingStream = computed(
        () =>
            streams.value.find(
                (stream) =>
                    stream.status === 'OPEN' && !stream.hasReceivedData,
            ) ?? null,
    )

    const health = computed<ControlCenterMonitoringHealth>(() => {
        if (closedStream.value) {
            return 'attention_needed'
        }
        if (connectingStream.value) {
            return 'reconnecting'
        }
        if (waitingStream.value) {
            return 'warming_up'
        }
        return 'healthy'
    })

    const statusTitle = computed(() => {
        if (closedStream.value) {
            return 'Monitoring needs attention'
        }
        if (connectingStream.value) {
            return 'Monitoring is reconnecting'
        }
        if (waitingStream.value) {
            return 'Monitoring is warming up'
        }
        return 'Monitoring is healthy'
    })

    const statusBody = computed(() => {
        if (closedStream.value) {
            return `${closedStream.value.label} stream is currently offline.`
        }
        if (connectingStream.value) {
            return `${connectingStream.value.label} stream is reconnecting while Moonwalker keeps watch.`
        }
        if (waitingStream.value) {
            return `${waitingStream.value.label} stream is open, but it is still waiting for the first payload.`
        }
        return 'Moonwalker is receiving live updates across all tracked streams.'
    })

    const alertTitle = computed(() => {
        if (closedStream.value) {
            return 'Stream health needs attention'
        }
        if (connectingStream.value) {
            return 'Realtime streams are reconnecting'
        }
        if (waitingStream.value) {
            return 'Streams are still warming up'
        }
        return null
    })

    const alertType = computed<'warning' | 'info'>(() => {
        if (closedStream.value) {
            return 'warning'
        }
        return 'info'
    })

    const featuredInsight = computed(() => {
        if (closedStream.value) {
            return `${closedStream.value.label} is down, so the full Monitoring page should be your next stop.`
        }
        if (connectingStream.value) {
            return `${connectingStream.value.label} is reconnecting, but the rest of the cockpit can keep running.`
        }
        if (waitingStream.value) {
            return `${waitingStream.value.label} is the only stream still waiting for its first payload.`
        }
        return 'All four realtime streams are open and receiving data.'
    })

    return {
        alertTitle,
        alertType,
        closedStream,
        connectingStream,
        featuredInsight,
        health,
        openCount,
        receivingCount,
        statusBody,
        statusTitle,
        streams,
        totalReconnects,
        totalStreams,
        waitingStream,
    }
}
